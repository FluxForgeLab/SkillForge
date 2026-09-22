"""C4.4: control/treatment aggregation and suite loop. No Docker."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.evaluation_runs import get_evaluation_run
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.skill_versions import insert_skill_version
from skillforge.db.repositories.skills import insert_skill
from skillforge.domain.entities import EvalCase, EvaluationRun, Project, Skill, SkillVersion
from skillforge.domain.enums import EvaluationRunStatus
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.evaluator.cases import LoadedEvalCase
from skillforge.evaluator.suite import run_suite, summarize
from skillforge.runtime.agent import RunResult
from skillforge.tracing.sink import TraceSink

_HEALTHY = {
    "http_status": 200,
    "backend_running": True,
    "nginx_config_valid": True,
    "upstream_port_matches": True,
    "db_running": True,
}


def test_summarize_uplift_from_mixed_trials() -> None:
    runs = [
        _run("c0", baseline=True, passed=True, latency=100, tool_errors=1, policy=0),
        _run("c1", baseline=True, passed=False, latency=300, tool_errors=0, policy=2),
        _run("t0", baseline=False, passed=True, latency=80, tool_errors=0, policy=0),
        _run("t1", baseline=False, passed=True, latency=120, tool_errors=0, policy=1),
    ]
    report = summarize(runs, skill_version_id="ver_1", repeats=2)
    assert report.control.trials == 2
    assert report.control.success_rate == 0.5
    assert report.control.avg_latency == 200
    assert report.control.tool_error_count == 1
    assert report.control.policy_violations == 2
    assert report.control.baseline is True
    assert report.treatment.success_rate == 1.0
    assert report.treatment.avg_latency == 100
    assert report.treatment.tool_error_count == 0
    assert report.treatment.policy_violations == 1
    assert report.treatment.baseline is False
    assert report.uplift_pp == 50


def test_summarize_rejects_a_missing_arm() -> None:
    runs = [_run("t0", baseline=False, passed=True, latency=10, tool_errors=0, policy=0)]
    with pytest.raises(ValueError, match="control arm has no trials"):
        summarize(runs, skill_version_id="ver_1", repeats=1)


async def test_suite_runs_control_then_treatment(tmp_path: Path) -> None:
    db_path = tmp_path / "eval.sqlite"
    version_id = _seed(db_path)
    seen: list[tuple[str, str | None]] = []

    def factory(run_id: str, sink: TraceSink) -> _RecordingHarness:
        del sink
        return _RecordingHarness(run_id, seen)

    report = await run_suite(
        [_loaded()],
        skill_path="skills/golden/service-recovery",
        skill_version_id=version_id,
        workspace=str(tmp_path),
        harness_factory=factory,
        db_path=db_path,
        repeats=2,
        suite_id="suite_unit",
        reset=lambda: None,
        inject=lambda _fault_id: None,
        verify=lambda: dict(_HEALTHY),
        settle_sec=0,
    )
    assert [item[1] for item in seen] == [
        None,
        "skills/golden/service-recovery",
        None,
        "skills/golden/service-recovery",
    ]
    assert [item[0] for item in seen] == [
        "suite_unit_eval_backend_stopped_control_0",
        "suite_unit_eval_backend_stopped_treatment_0",
        "suite_unit_eval_backend_stopped_control_1",
        "suite_unit_eval_backend_stopped_treatment_1",
    ]
    assert [run.baseline["baseline"] for run in report.runs] == [True, False, True, False]
    assert report.uplift_pp == 0
    assert report.control.success_rate == 1
    assert report.treatment.success_rate == 1
    with connection(db_path) as conn:
        stored = get_evaluation_run(conn, seen[0][0])
    assert stored is not None
    assert stored.baseline == {"baseline": True}
    assert stored.skill_version_id == version_id


async def test_repeats_below_one_raises(tmp_path: Path) -> None:
    def factory(run_id: str, sink: TraceSink) -> _RecordingHarness:
        del run_id, sink
        raise AssertionError("factory should not be called")

    with pytest.raises(ValueError, match="repeats must be >= 1"):
        await run_suite(
            [_loaded()],
            skill_path="skills/golden/service-recovery",
            skill_version_id="ver_1",
            workspace=str(tmp_path),
            harness_factory=factory,
            db_path=tmp_path / "eval.sqlite",
            repeats=0,
        )


class _RecordingHarness:
    def __init__(self, run_id: str, seen: list[tuple[str, str | None]]) -> None:
        self._run_id = run_id
        self._seen = seen

    async def run(self, task: str, skill_path: str | None, workspace: str) -> RunResult:
        del task, workspace
        self._seen.append((self._run_id, skill_path))
        return RunResult(
            run_id=self._run_id,
            status="completed",
            final_content="ok",
            steps=1,
            tool_errors=0,
            tokens=1,
            latency_ms=10,
            policy_violations=0,
        )


def _loaded() -> LoadedEvalCase:
    case = EvalCase(
        id="eval_backend_stopped",
        name="backend process stopped",
        task="Restore it.",
        fixture="backend_stopped",
        expected=dict(_HEALTHY),
        forbidden=["delete_volume", "restart_database"],
        timeout_sec=30,
    )
    return LoadedEvalCase(case=case, fault_id="backend_stopped")


def _run(
    run_id: str,
    *,
    baseline: bool,
    passed: bool,
    latency: int,
    tool_errors: int,
    policy: int,
) -> EvaluationRun:
    now = datetime.now(UTC)
    return EvaluationRun(
        id=run_id,
        skill_version_id="ver_1",
        baseline={"baseline": baseline},
        metrics={
            "passed": passed,
            "latency_ms": latency,
            "tool_errors": tool_errors,
            "policy_violations": policy,
        },
        status=EvaluationRunStatus.COMPLETED,
        started_at=now,
        finished_at=now,
    )


def _seed(db_path: Path) -> str:
    initialize_database(db_path)
    now = datetime.now(UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id="proj_1", name="lab", created_at=now))
        insert_skill(conn, Skill(id="skill_1", project_id="proj_1", name="service-recovery"))
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
