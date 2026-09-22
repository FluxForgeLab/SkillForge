"""C4.3: one case runner persists an EvaluationRun. No Docker."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.evaluation_runs import get_evaluation_run
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.skill_versions import insert_skill_version
from skillforge.db.repositories.skills import insert_skill
from skillforge.domain.entities import EvalCase, Project, Skill, SkillVersion, TraceEvent
from skillforge.domain.enums import EvaluationRunStatus, TraceEventType
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.evaluator.cases import LoadedEvalCase
from skillforge.evaluator.runner import run_case
from skillforge.runtime.agent import RunResult

_HEALTHY = {
    "http_status": 200,
    "backend_running": True,
    "nginx_config_valid": True,
    "upstream_port_matches": True,
    "db_running": True,
}


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


class SlowHarness:
    def __init__(self) -> None:
        self.destroyed = False

    async def run(self, task: str, skill_path: str | None, workspace: str) -> RunResult:
        del task, skill_path, workspace
        try:
            await asyncio.sleep(30)
        finally:
            self.destroyed = True
        raise AssertionError("harness should have been cancelled")


class DoneHarness:
    def __init__(self, status: Literal["completed", "exhausted"] = "completed") -> None:
        self.status: Literal["completed", "exhausted"] = status

    async def run(self, task: str, skill_path: str | None, workspace: str) -> RunResult:
        del task, skill_path, workspace
        return RunResult(
            run_id="evalrun_ok",
            status=self.status,
            final_content="recovered",
            steps=4,
            tool_errors=0,
            tokens=5,
            latency_ms=12,
            policy_violations=0,
        )


async def test_timeout_fails_and_destroys_sandbox(tmp_path: Path) -> None:
    db_path = tmp_path / "eval.sqlite"
    version_id = _seed(db_path)
    harness = SlowHarness()
    sink = ListSink()
    calls = {"reset": 0, "inject": []}

    def reset() -> None:
        calls["reset"] += 1

    def inject(fault_id: str) -> None:
        calls["inject"].append(fault_id)

    record = await run_case(
        _loaded(timeout_sec=1),
        run_id="evalrun_timeout",
        skill_path="skills/golden/service-recovery",
        skill_version_id=version_id,
        workspace=str(tmp_path),
        harness=harness,
        sink=sink,
        db_path=db_path,
        reset=reset,
        inject=inject,
        verify=lambda: dict(_HEALTHY),
    )
    assert harness.destroyed is True
    assert calls["reset"] == 2
    assert calls["inject"] == ["backend_stopped"]
    assert record.status == EvaluationRunStatus.FAILED
    assert record.baseline == {"baseline": False}
    assert record.metrics["timed_out"] is True
    assert record.metrics["agent_status"] == "timeout"
    assert record.metrics["passed"] is True
    assert sink.events[-1].type == TraceEventType.ASSERTION
    with connection(db_path) as conn:
        stored = get_evaluation_run(conn, "evalrun_timeout")
    assert stored is not None
    assert stored.model_dump() == record.model_dump()


async def test_matching_verifier_completes(tmp_path: Path) -> None:
    db_path = tmp_path / "eval.sqlite"
    version_id = _seed(db_path)
    sink = ListSink()
    record = await run_case(
        _loaded(),
        run_id="evalrun_ok",
        skill_path="skills/golden/service-recovery",
        skill_version_id=version_id,
        workspace=str(tmp_path),
        harness=DoneHarness(),
        sink=sink,
        db_path=db_path,
        reset=lambda: None,
        inject=lambda _fault_id: None,
        verify=lambda: dict(_HEALTHY),
    )
    assert record.status == EvaluationRunStatus.COMPLETED
    assert record.metrics["passed"] is True
    assert record.metrics["agent_status"] == "completed"
    assert record.metrics["steps"] == 4
    assert record.metrics["tokens"] == 5
    assert record.metrics["timed_out"] is False
    assert sink.events[-1].output["passed"] is True


async def test_verifier_mismatch_completes_with_passed_false(tmp_path: Path) -> None:
    db_path = tmp_path / "eval.sqlite"
    version_id = _seed(db_path)
    verifier = dict(_HEALTHY)
    verifier["http_status"] = 502
    record = await run_case(
        _loaded(),
        run_id="evalrun_miss",
        skill_path="skills/golden/service-recovery",
        skill_version_id=version_id,
        workspace=str(tmp_path),
        harness=DoneHarness("exhausted"),
        sink=ListSink(),
        db_path=db_path,
        reset=lambda: None,
        inject=lambda _fault_id: None,
        verify=lambda: verifier,
        settle_sec=0,
    )
    assert record.status == EvaluationRunStatus.COMPLETED
    assert record.metrics["passed"] is False
    assert record.metrics["agent_status"] == "exhausted"


def _loaded(*, timeout_sec: int = 180) -> LoadedEvalCase:
    case = EvalCase(
        id="eval_backend_stopped",
        name="backend process stopped",
        task="Restore it.",
        fixture="backend_stopped",
        expected=dict(_HEALTHY),
        forbidden=["delete_volume", "restart_database"],
        timeout_sec=timeout_sec,
    )
    return LoadedEvalCase(case=case, fault_id="backend_stopped")


def _seed(db_path: Path) -> str:
    initialize_database(db_path)
    now = datetime.now(UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id="proj_1", name="lab", created_at=now))
        insert_skill(
            conn,
            Skill(id="skill_1", project_id="proj_1", name="service-recovery"),
        )
        insert_skill_version(
            conn,
            SkillVersion(
                id="ver_1",
                skill_id="skill_1",
                version="0.1",
                status=SkillVersionStatus.DRAFT,
                artifact_path="skills/golden/service-recovery",
                created_at=now,
            ),
        )
    return "ver_1"
