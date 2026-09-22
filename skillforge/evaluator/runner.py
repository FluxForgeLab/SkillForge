"""Run one eval case: reset, inject, agent, verifier, assertion, EvaluationRun."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.evaluation_runs import insert_evaluation_run
from skillforge.domain.entities import EvaluationRun, TraceEvent
from skillforge.domain.enums import EvaluationRunStatus
from skillforge.evaluator.assertions import assert_case
from skillforge.evaluator.cases import LoadedEvalCase
from skillforge.evaluator.errors import EvalGuardError
from skillforge.evaluator.guard import verify_sealed_evals
from skillforge.runtime.agent import AgentRuntime
from skillforge.tracing.sink import TraceSink

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RESET_SCRIPT = _REPO_ROOT / "demo" / "ops-lab" / "faults" / "reset.py"
_INJECT_SCRIPT = _REPO_ROOT / "demo" / "ops-lab" / "faults" / "inject.py"
_VERIFY_SCRIPT = _REPO_ROOT / "demo" / "ops-lab" / "verifier" / "verify.py"
_SETTLE_SEC = 30.0
_SETTLE_INTERVAL_SEC = 0.5

ResetFn = Callable[[], None]
InjectFn = Callable[[str], None]
VerifyFn = Callable[[], Mapping[str, Any]]


async def run_case(
    loaded: LoadedEvalCase,
    *,
    run_id: str,
    skill_path: str | None,
    skill_version_id: str,
    workspace: str,
    harness: AgentRuntime,
    sink: TraceSink,
    db_path: Path,
    reset: ResetFn | None = None,
    inject: InjectFn | None = None,
    verify: VerifyFn | None = None,
    settle_sec: float = _SETTLE_SEC,
    baseline: bool = False,
    evals_dir: str | Path | None = None,
) -> EvaluationRun:
    """Execute one case and insert its EvaluationRun.

    ``sink`` must keep written events on ``sink.events`` so forbidden checks can see tool calls.
    The harness must use the same ``run_id`` and sink. ``skill_version_id`` must already exist.
    ``skill_path=None`` is the control arm. ``baseline`` is stored on the evaluation row.
    ``evals_dir`` (or ``skill_path`` when set) is checked against a candidate eval seal
    before inject.
    """
    reset_lab = reset if reset is not None else _reset_lab
    inject_lab = inject if inject is not None else _inject_lab
    read_verifier = verify if verify is not None else _verify_lab
    sealed_dir: Path | None
    if evals_dir is not None:
        sealed_dir = Path(evals_dir)
    elif skill_path is not None:
        sealed_dir = Path(skill_path)
    else:
        sealed_dir = None
    if sealed_dir is not None:
        verify_sealed_evals(db_path, skill_version_id, sealed_dir)
    started_at = datetime.now(UTC)
    timed_out = False
    passed = False
    agent_status = "error"
    steps = 0
    tool_errors = 0
    tokens = 0
    latency_ms = 0
    policy_violations = 0
    status = EvaluationRunStatus.FAILED
    try:
        reset_lab()
        inject_lab(loaded.fault_id)
        try:
            result = await asyncio.wait_for(
                harness.run(loaded.case.task, skill_path, workspace),
                loaded.case.timeout_sec,
            )
        except TimeoutError:
            timed_out = True
            agent_status = "timeout"
        else:
            agent_status = result.status
            steps = result.steps
            tool_errors = result.tool_errors
            tokens = result.tokens
            latency_ms = result.latency_ms
            policy_violations = result.policy_violations
        snapshot = await _settle_verifier(read_verifier, loaded.case.expected, settle_sec)
        assertion = await assert_case(
            loaded.case,
            snapshot,
            _sink_events(sink),
            run_id=run_id,
            sink=sink,
        )
        passed = assertion.passed
        status = EvaluationRunStatus.FAILED if timed_out else EvaluationRunStatus.COMPLETED
    except EvalGuardError:
        raise
    except Exception:
        logger.exception("eval case %s failed", loaded.case.id)
        status = EvaluationRunStatus.FAILED
    finally:
        try:
            reset_lab()
        except Exception:
            logger.exception("eval case %s reset failed", loaded.case.id)
            status = EvaluationRunStatus.FAILED
    record = EvaluationRun(
        id=run_id,
        skill_version_id=skill_version_id,
        baseline={"baseline": baseline},
        metrics=_metrics(
            loaded,
            passed=passed,
            agent_status=agent_status,
            steps=steps,
            tool_errors=tool_errors,
            tokens=tokens,
            latency_ms=latency_ms,
            policy_violations=policy_violations,
            timed_out=timed_out,
        ),
        status=status,
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
    initialize_database(db_path)
    with connection(db_path) as conn:
        insert_evaluation_run(conn, record)
    return record


def _metrics(
    loaded: LoadedEvalCase,
    *,
    passed: bool,
    agent_status: str,
    steps: int,
    tool_errors: int,
    tokens: int,
    latency_ms: int,
    policy_violations: int,
    timed_out: bool,
) -> dict[str, Any]:
    return {
        "case_id": loaded.case.id,
        "fault_id": loaded.fault_id,
        "passed": passed,
        "agent_status": agent_status,
        "steps": steps,
        "tool_errors": tool_errors,
        "tokens": tokens,
        "latency_ms": latency_ms,
        "policy_violations": policy_violations,
        "timed_out": timed_out,
    }


async def _settle_verifier(
    verify: VerifyFn,
    expected: Mapping[str, Any],
    settle_sec: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + settle_sec
    last: dict[str, Any] = {}
    while True:
        snapshot = verify()
        last = dict(snapshot)
        if _expected_matches(last, expected) or time.monotonic() >= deadline:
            return last
        await asyncio.sleep(_SETTLE_INTERVAL_SEC)


def _expected_matches(snapshot: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    for key, want in expected.items():
        if key not in snapshot or not _values_equal(want, snapshot[key]):
            return False
    return True


def _values_equal(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(expected) is type(actual) and expected == actual
    return expected == actual


def _sink_events(sink: TraceSink) -> list[TraceEvent]:
    events = getattr(sink, "events", None)
    if isinstance(events, list):
        return events
    return []


def _reset_lab() -> None:
    completed = subprocess.run([sys.executable, str(_RESET_SCRIPT)], check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"ops-lab reset failed with exit {completed.returncode}")


def _inject_lab(fault_id: str) -> None:
    completed = subprocess.run([sys.executable, str(_INJECT_SCRIPT), fault_id], check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"ops-lab inject {fault_id} failed with exit {completed.returncode}")


def _verify_lab() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(_VERIFY_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = completed.stdout.strip()
    if not stdout:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"verifier produced no JSON: {detail}")
    payload = json.loads(stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("verifier JSON must be an object")
    return payload
