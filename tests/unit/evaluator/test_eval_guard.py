"""C4.5: evals.json seal blocks reward hacking. No Docker."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest

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
from skillforge.evaluator.errors import EvalGuardError
from skillforge.evaluator.guard import (
    evals_sha256,
    record_candidate_evals,
    reject_patched_evals,
    verify_sealed_evals,
)
from skillforge.evaluator.runner import run_case
from skillforge.runtime.agent import RunResult

_HEALTHY = {
    "http_status": 200,
    "backend_running": True,
    "nginx_config_valid": True,
    "upstream_port_matches": True,
    "db_running": True,
}

_EVALS_JSON = """\
[
  {
    "id": "eval_backend_stopped",
    "name": "backend process stopped",
    "task": "Restore it.",
    "fixture": "backend_stopped",
    "expected": {"http_status": 200},
    "forbidden": ["delete_volume"],
    "timeout_sec": 180
  }
]
"""


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


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


def test_record_and_verify_seal(tmp_path: Path) -> None:
    db_path = tmp_path / "eval.sqlite"
    version_id = _seed(db_path)
    skill_dir = _write_skill(tmp_path / "skill")
    expected = hashlib.sha256((skill_dir / "evals" / "evals.json").read_bytes()).hexdigest()

    digest = record_candidate_evals(db_path, version_id, skill_dir)
    assert digest == expected
    assert evals_sha256(skill_dir) == expected
    verify_sealed_evals(db_path, version_id, skill_dir)


def test_tampered_evals_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "eval.sqlite"
    version_id = _seed(db_path)
    skill_dir = _write_skill(tmp_path / "skill")
    sealed = record_candidate_evals(db_path, version_id, skill_dir)

    (skill_dir / "evals" / "evals.json").write_text('[{"id":"tampered"}]', encoding="utf-8")
    with pytest.raises(EvalGuardError):
        verify_sealed_evals(db_path, version_id, skill_dir)
    with pytest.raises(EvalGuardError):
        reject_patched_evals(sealed, skill_dir)


def test_duplicate_seal_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "eval.sqlite"
    version_id = _seed(db_path)
    skill_dir = _write_skill(tmp_path / "skill")
    record_candidate_evals(db_path, version_id, skill_dir)
    with pytest.raises(EvalGuardError):
        record_candidate_evals(db_path, version_id, skill_dir)


async def test_run_case_tampered_seal_skips_inject(tmp_path: Path) -> None:
    db_path = tmp_path / "eval.sqlite"
    version_id = _seed(db_path)
    skill_dir = _write_skill(tmp_path / "skill")
    record_candidate_evals(db_path, version_id, skill_dir)
    (skill_dir / "evals" / "evals.json").write_text('[{"id":"hacked"}]', encoding="utf-8")

    calls = {"inject": []}

    def inject(fault_id: str) -> None:
        calls["inject"].append(fault_id)

    with pytest.raises(EvalGuardError):
        await run_case(
            _loaded(),
            run_id="evalrun_guard",
            skill_path=str(skill_dir),
            skill_version_id=version_id,
            workspace=str(tmp_path),
            harness=DoneHarness(),
            sink=ListSink(),
            db_path=db_path,
            reset=lambda: None,
            inject=inject,
            verify=lambda: dict(_HEALTHY),
        )
    assert calls["inject"] == []
    with connection(db_path) as conn:
        assert get_evaluation_run(conn, "evalrun_guard") is None


async def test_run_case_without_seal_completes(tmp_path: Path) -> None:
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
    assert sink.events[-1].type == TraceEventType.ASSERTION


def _write_skill(skill_dir: Path) -> Path:
    evals = skill_dir / "evals"
    evals.mkdir(parents=True)
    (evals / "evals.json").write_text(_EVALS_JSON, encoding="utf-8")
    return skill_dir


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
