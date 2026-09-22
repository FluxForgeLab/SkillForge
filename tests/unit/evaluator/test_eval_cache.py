"""C4.8: eval result cache store and replay. No Docker."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.skill_versions import insert_skill_version
from skillforge.db.repositories.skills import insert_skill
from skillforge.domain.entities import EvalCase, Project, Skill, SkillVersion
from skillforge.domain.enums import EvaluationRunStatus
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.evaluator.cache import load_trial, replay_trials, store_trial
from skillforge.evaluator.cases import LoadedEvalCase
from skillforge.evaluator.errors import CacheMiss
from skillforge.evaluator.suite import run_suite
from skillforge.runtime.agent import RunResult
from skillforge.tracing.sink import TraceSink

_HEALTHY = {
    "http_status": 200,
    "backend_running": True,
    "nginx_config_valid": True,
    "upstream_port_matches": True,
    "db_running": True,
}
_METRICS = {
    "case_id": "eval_backend_stopped",
    "fault_id": "backend_stopped",
    "passed": True,
    "agent_status": "completed",
    "steps": 1,
    "tool_errors": 0,
    "tokens": 2,
    "latency_ms": 10,
    "policy_violations": 0,
    "timed_out": False,
}


def test_store_then_replay_preserves_passed(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.sqlite"
    store_trial(
        db_path,
        version_hash="abc",
        case_id="eval_backend_stopped",
        arm="control",
        model="fake-model",
        baseline=True,
        metrics={**_METRICS, "passed": False},
        status=EvaluationRunStatus.COMPLETED.value,
    )
    store_trial(
        db_path,
        version_hash="abc",
        case_id="eval_backend_stopped",
        arm="treatment",
        model="fake-model",
        baseline=False,
        metrics={**_METRICS, "passed": True},
        status=EvaluationRunStatus.COMPLETED.value,
    )
    runs = replay_trials(
        db_path,
        version_hash="abc",
        model="fake-model",
        case_ids=["eval_backend_stopped"],
    )
    assert len(runs) == 2
    assert runs[0].baseline == {"baseline": True}
    assert runs[0].metrics["passed"] is False
    assert runs[1].baseline == {"baseline": False}
    assert runs[1].metrics["passed"] is True
    assert runs[0].id == "replay_abc_eval_backend_stopped_control"
    assert runs[1].skill_version_id == "replay"


def test_missing_treatment_raises_cache_miss(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.sqlite"
    store_trial(
        db_path,
        version_hash="abc",
        case_id="eval_backend_stopped",
        arm="control",
        model="fake-model",
        baseline=True,
        metrics=dict(_METRICS),
        status=EvaluationRunStatus.COMPLETED.value,
    )
    with pytest.raises(CacheMiss, match="treatment") as caught:
        replay_trials(
            db_path,
            version_hash="abc",
            model="fake-model",
            case_ids=["eval_backend_stopped"],
        )
    assert caught.value.case_id == "eval_backend_stopped"
    assert caught.value.arm == "treatment"


async def test_run_suite_writes_cache_and_replay_skips_harness(tmp_path: Path) -> None:
    db_path = tmp_path / "eval.sqlite"
    version_id = _seed(db_path)

    def factory(run_id: str, sink: TraceSink) -> _RecordingHarness:
        del sink
        return _RecordingHarness(run_id)

    report = await run_suite(
        [_loaded()],
        skill_path="skills/golden/service-recovery",
        skill_version_id=version_id,
        workspace=str(tmp_path),
        harness_factory=factory,
        db_path=db_path,
        repeats=1,
        suite_id="suite_cache",
        reset=lambda: None,
        inject=lambda _fault_id: None,
        verify=lambda: dict(_HEALTHY),
        settle_sec=0,
        version_hash="abc",
        model="fake-model",
        replay=False,
    )
    assert report.control.success_rate == 1
    assert report.treatment.success_rate == 1
    with connection(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM eval_cache").fetchone()
    assert count is not None and count[0] == 2
    control = load_trial(
        db_path,
        version_hash="abc",
        case_id="eval_backend_stopped",
        arm="control",
        model="fake-model",
    )
    treatment = load_trial(
        db_path,
        version_hash="abc",
        case_id="eval_backend_stopped",
        arm="treatment",
        model="fake-model",
    )
    assert control is not None and control["baseline"] is True
    assert treatment is not None and treatment["baseline"] is False

    def boom(run_id: str, sink: TraceSink) -> _RecordingHarness:
        del run_id, sink
        raise AssertionError("factory should not be called")

    replayed = await run_suite(
        [_loaded()],
        skill_path="skills/golden/service-recovery",
        skill_version_id=version_id,
        workspace=str(tmp_path),
        harness_factory=boom,
        db_path=db_path,
        repeats=1,
        reset=lambda: (_ for _ in ()).throw(AssertionError("reset")),
        inject=lambda _fault_id: (_ for _ in ()).throw(AssertionError("inject")),
        verify=lambda: (_ for _ in ()).throw(AssertionError("verify")),
        settle_sec=0,
        version_hash="abc",
        model="fake-model",
        replay=True,
    )
    assert replayed.control.success_rate == 1
    assert replayed.treatment.success_rate == 1
    assert replayed.uplift_pp == 0
    assert replayed.skill_version_id == version_id


class _RecordingHarness:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id

    async def run(self, task: str, skill_path: str | None, workspace: str) -> RunResult:
        del task, skill_path, workspace
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
