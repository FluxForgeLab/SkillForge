"""C7.7: evolve / approve / publish / version-diff API endpoints."""

from __future__ import annotations

import difflib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from starlette.testclient import TestClient

from skillforge.api.main import create_app
from skillforge.api.routers.evolution import (
    get_evolve_analyze,
    get_evolve_propose,
    get_evolve_suite_pair,
)
from skillforge.api.routers.skills import get_compile_gateway
from skillforge.config import Settings
from skillforge.db import initialize_database
from skillforge.db.connection import connection
from skillforge.db.repositories.projects import insert_project
from skillforge.domain.entities import EvaluationRun, Failure, PatchProposal, Project
from skillforge.domain.enums import EvaluationRunStatus, FailureClass
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.evaluator.suite import ArmSummary, SuiteReport
from skillforge.evolution.apply import apply_patch
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.registry.service import SkillRegistry
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import SqliteTraceSink

_SKILL_MD_V01 = """\
---
name: service-recovery-mini
description: Mini skill for evolve API tests.
version: 0.1.0
triggers: [HTTP 502]
tools: [docker.inspect, docker.restart, http.get]
permissions:
  filesystem: {read: [/workspace], write: [/workspace/runtime]}
  network: {allow: [localhost]}
  shell: {destructive_commands: false}
---

# Service Recovery Mini

## Procedure

ins_01 docker.inspect backend.
ins_02 If stopped, docker.restart backend.
ins_03 http.get http://127.0.0.1:8088/health.
"""

_EVALS = """\
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

_SOURCE_MAP_V01 = {
    "ins_01": {
        "knowledge_unit_id": "ku_down",
        "document": "runbook.md",
        "sha256": "abc123",
        "line_start": 1,
    },
    "ins_02": {
        "knowledge_unit_id": "ku_down",
        "document": "runbook.md",
        "sha256": "abc123",
        "line_start": 2,
    },
    "ins_03": {
        "knowledge_unit_id": "ku_down",
        "document": "runbook.md",
        "sha256": "abc123",
        "line_start": 3,
    },
}


def test_evolve_creates_candidate_when_gate_passes(tmp_path: Path) -> None:
    client, registry, parent = _client_with_skill(tmp_path)
    new_md = _with_instruction("ins_08 Run nginx -t before reload.")
    proposal = PatchProposal(
        diff=_unified(_SKILL_MD_V01, new_md),
        summary="Add nginx -t",
        target_skill_version_id=parent.id,
        evidence_refs=["doc#appendix-b"],
    )
    failure = Failure(
        run_id="run_fail",
        failure_class=FailureClass.MISSING_INSTRUCTION,
        symptom="F3 still failing",
        failed_assertion="http_status",
        evidence=["502"],
        source_support=["runbook.md#page=2"],
    )

    async def fake_analyze(**_kwargs: object) -> Failure:
        return failure

    async def fake_propose(**_kwargs: object) -> PatchProposal:
        return proposal

    async def fake_suites(**kwargs: object) -> tuple[SuiteReport, SuiteReport]:
        return (
            _suite(
                kwargs["parent_version_id"],
                treatment_rate=0.0,
                failed_run_id="run_fail",
                case_passed=False,
            ),
            _suite(
                kwargs["candidate_version_id"],
                treatment_rate=1.0,
                failed_run_id="run_fail_fixed",
                case_passed=True,
            ),
        )

    app = client.app
    app.dependency_overrides[get_evolve_analyze] = lambda: fake_analyze
    app.dependency_overrides[get_evolve_propose] = lambda: fake_propose
    app.dependency_overrides[get_evolve_suite_pair] = lambda: fake_suites

    response = client.post(
        f"/api/skills/{parent.skill_id}/evolve",
        json={
            "version": "0.2",
            "run_id": "run_fail",
            "assertion": {"passed": False, "mismatches": [], "forbidden_hits": []},
            "verifier": {"http_status": 502},
            "events": [],
            "source_map_updates": {
                "ins_08": {
                    "knowledge_unit_id": "ku_appendix",
                    "document": "runbook.md",
                    "sha256": "abc123",
                    "page": 12,
                }
            },
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CANDIDATE"
    assert body["parent_version_id"] == parent.id
    assert body["gate"]["passed"] is True
    created = registry.get_version(body["version_id"])
    assert created.status == SkillVersionStatus.CANDIDATE
    assert created.parent_version_id == parent.id


def test_evolve_stays_draft_when_gate_fails(tmp_path: Path) -> None:
    client, registry, parent = _client_with_skill(tmp_path)
    new_md = _with_instruction("ins_08 Run nginx -t before reload.")
    proposal = PatchProposal(
        diff=_unified(_SKILL_MD_V01, new_md),
        summary="Add nginx -t",
        target_skill_version_id=parent.id,
    )
    failure = Failure(
        run_id="run_fail",
        failure_class=FailureClass.MISSING_INSTRUCTION,
        symptom="still broken",
        evidence=["502"],
        source_support=[],
    )

    async def fake_analyze(**_kwargs: object) -> Failure:
        return failure

    async def fake_propose(**_kwargs: object) -> PatchProposal:
        return proposal

    async def fake_suites(**kwargs: object) -> tuple[SuiteReport, SuiteReport]:
        return (
            _suite(kwargs["parent_version_id"], treatment_rate=1.0),
            _suite(kwargs["candidate_version_id"], treatment_rate=0.5),
        )

    app = client.app
    app.dependency_overrides[get_evolve_analyze] = lambda: fake_analyze
    app.dependency_overrides[get_evolve_propose] = lambda: fake_propose
    app.dependency_overrides[get_evolve_suite_pair] = lambda: fake_suites

    response = client.post(
        f"/api/skills/{parent.skill_id}/evolve",
        json={
            "version": "0.2",
            "run_id": "run_fail",
            "assertion": {"passed": False, "mismatches": [], "forbidden_hits": []},
            "verifier": {},
            "events": [],
            "source_map_updates": {
                "ins_08": {
                    "knowledge_unit_id": "ku_appendix",
                    "document": "runbook.md",
                    "sha256": "abc123",
                    "page": 12,
                }
            },
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["gate"]["passed"] is False
    assert registry.get_version(body["version_id"]).status == SkillVersionStatus.DRAFT


def test_approve_publish_and_diff(tmp_path: Path) -> None:
    client, registry, parent = _client_with_skill(tmp_path)
    new_md = _with_instruction("ins_08 Run nginx -t before reload.")
    proposal = PatchProposal(diff=_unified(_SKILL_MD_V01, new_md), summary="patch")
    updates = {
        "ins_08": {
            "knowledge_unit_id": "ku_appendix",
            "document": "runbook.md",
            "sha256": "abc123",
            "page": 12,
        }
    }
    parent_dir = Path(parent.artifact_path)  # type: ignore[arg-type]
    child = apply_patch(
        registry,
        parent_version_id=parent.id,
        parent_dir=parent_dir,
        proposal=proposal,
        source_map_updates=updates,
        version="0.2",
    )
    registry.transition(child.id, SkillVersionStatus.CANDIDATE)

    missing = client.post(
        f"/api/skills/{parent.skill_id}/versions/{child.id}/approve",
        json={},
    )
    assert missing.status_code == 422

    empty = client.post(
        f"/api/skills/{parent.skill_id}/versions/{child.id}/approve",
        json={"approver": ""},
    )
    assert empty.status_code == 422

    approved = client.post(
        f"/api/skills/{parent.skill_id}/versions/{child.id}/approve",
        json={"approver": "alice"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approver"] == "alice"

    published = client.post(f"/api/skills/{parent.skill_id}/versions/{child.id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "PUBLISHED"
    assert Path(published.json()["published_path"]).is_dir()

    diff = client.get(f"/api/skills/{parent.skill_id}/versions/{child.id}/diff")
    assert diff.status_code == 200
    body = diff.json()
    assert body["has_parent"] is True
    assert body["parent_version_id"] == parent.id
    assert "ins_08" in body["diff"]
    assert "SKILL.md" in body["diff"]


def test_approve_unknown_and_publish_illegal_state(tmp_path: Path) -> None:
    client, _registry, parent = _client_with_skill(tmp_path)

    assert (
        client.post(
            f"/api/skills/{parent.skill_id}/versions/missing/approve",
            json={"approver": "bob"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/skills/missing/versions/missing/approve",
            json={"approver": "bob"},
        ).status_code
        == 404
    )
    illegal = client.post(f"/api/skills/{parent.skill_id}/versions/{parent.id}/publish")
    assert illegal.status_code == 409

    no_parent = client.get(f"/api/skills/{parent.skill_id}/versions/{parent.id}/diff")
    assert no_parent.status_code == 200
    assert no_parent.json()["has_parent"] is False
    assert no_parent.json()["diff"] == ""


def test_evolve_unknown_skill_is_404(tmp_path: Path) -> None:
    client, _, _ = _client_with_skill(tmp_path)
    response = client.post(
        "/api/skills/missing/evolve",
        json={
            "version": "0.2",
            "run_id": "run_fail",
            "assertion": {"passed": False, "mismatches": [], "forbidden_hits": []},
        },
    )
    assert response.status_code == 404


def _client_with_skill(
    tmp_path: Path,
) -> tuple[TestClient, SkillRegistry, object]:
    db_path = tmp_path / "api_evolve.sqlite"
    initialize_database(db_path)
    project_id = f"proj_{uuid4().hex}"
    with connection(db_path) as conn:
        insert_project(
            conn,
            Project(id=project_id, name="lab", created_at=datetime.now(UTC)),
        )
    settings = Settings(
        _env_file=None,
        sqlite_path=db_path,
        data_dir=tmp_path / "data",
        skills_generated_dir=tmp_path / "generated",
        skills_published_dir=tmp_path / "published",
    )
    registry = SkillRegistry(
        db_path,
        generated_root=settings.skills_generated_dir,
        published_root=settings.skills_published_dir,
        settings=settings,
    )
    skill = registry.create_skill(project_id, "service-recovery-mini")
    files = {
        "SKILL.md": _SKILL_MD_V01.encode("utf-8"),
        "evals/evals.json": _EVALS.encode("utf-8"),
        "scripts/diagnose.py": b'print("diagnose")\n',
        "references/source-map.json": (
            json.dumps(_SOURCE_MAP_V01, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8"),
    }
    parent = registry.create_version(skill.id, "0.1", files)
    registry.transition(parent.id, SkillVersionStatus.CANDIDATE)

    gateway = ModelGateway(
        FakeModelAdapter([]),
        settings=settings,
        sink=SqliteTraceSink(db_path),
        bus=EventBus(),
    )
    app = create_app(settings, bus=EventBus())
    app.dependency_overrides[get_compile_gateway] = lambda: gateway
    return TestClient(app), registry, parent


def _with_instruction(line: str) -> str:
    return _SKILL_MD_V01.replace(
        "ins_03 http.get http://127.0.0.1:8088/health.\n",
        "ins_03 http.get http://127.0.0.1:8088/health.\n" + line + "\n",
    )


def _unified(old: str, new: str, *, path: str = "SKILL.md") -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )


def _suite(
    version_id: object,
    *,
    treatment_rate: float,
    failed_run_id: str = "run_fail",
    case_passed: bool | None = None,
) -> SuiteReport:
    passed = case_passed if case_passed is not None else treatment_rate >= 1.0
    now = datetime.now(UTC)
    treatment = EvaluationRun(
        id=failed_run_id,
        skill_version_id=str(version_id),
        baseline={"baseline": False},
        metrics={
            "case_id": "eval_f3",
            "passed": passed,
            "forbidden_hits": 0,
        },
        status=EvaluationRunStatus.COMPLETED,
        started_at=now,
        finished_at=now,
    )
    control = EvaluationRun(
        id=f"ctrl_{failed_run_id}",
        skill_version_id=str(version_id),
        baseline={"baseline": True},
        metrics={"case_id": "eval_f3", "passed": False, "forbidden_hits": 0},
        status=EvaluationRunStatus.COMPLETED,
        started_at=now,
        finished_at=now,
    )
    return SuiteReport(
        skill_version_id=str(version_id),
        repeats=1,
        uplift_pp=treatment_rate * 100,
        control=ArmSummary(
            baseline=True,
            trials=1,
            success_rate=0.0,
            avg_latency=0.0,
            tool_error_count=0,
            policy_violations=0,
        ),
        treatment=ArmSummary(
            baseline=False,
            trials=1,
            success_rate=treatment_rate,
            avg_latency=10.0,
            tool_error_count=0,
            policy_violations=0,
        ),
        runs=[control, treatment],
    )
