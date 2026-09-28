"""C6.8: compile, read, and validate a skill through the API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from starlette.testclient import TestClient

from skillforge.api.main import create_app
from skillforge.api.routers.skills import get_compile_gateway
from skillforge.config import Settings
from skillforge.db import initialize_database
from skillforge.db.connection import connection
from skillforge.db.repositories.knowledge_units import insert_knowledge_unit
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.skill_versions import insert_skill_version
from skillforge.db.repositories.skills import insert_skill
from skillforge.db.repositories.source_documents import insert_source_document
from skillforge.domain.entities import KnowledgeUnit, Project, Skill, SkillVersion, SourceDocument
from skillforge.domain.enums import KnowledgeUnitType
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import SqliteTraceSink

_PROJECT = "proj_api"
_DOCUMENT = "doc_runbook"
_UNIT = "ku_down"


def test_compile_then_read_and_validate(tmp_path: Path) -> None:
    client, gateway = _client(tmp_path)
    app = client.app
    app.dependency_overrides[get_compile_gateway] = lambda: gateway
    response = client.post(
        f"/api/projects/{_PROJECT}/skills/compile",
        json={
            "name": "service-recovery",
            "description": "Diagnose and recover the edge service.",
            "triggers": ["backend unavailable"],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CANDIDATE"
    skill_id = body["skill_id"]

    detail = client.get(f"/api/skills/{skill_id}")
    assert detail.status_code == 200
    assert detail.json()["current_version_id"] == body["version_id"]
    assert detail.json()["status"] == "CANDIDATE"

    versions = client.get(f"/api/skills/{skill_id}/versions")
    assert versions.status_code == 200
    assert versions.json()[0]["id"] == body["version_id"]
    assert versions.json()[0]["parent_version_id"] is None

    validated = client.post(f"/api/skills/{skill_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["passed"] is True


def test_list_versions_includes_parent_version_id(tmp_path: Path) -> None:
    """C9.9: VersionResponse projects stored parent_version_id (no schema change)."""
    client, gateway = _client(tmp_path)
    client.app.dependency_overrides[get_compile_gateway] = lambda: gateway
    compiled = client.post(
        f"/api/projects/{_PROJECT}/skills/compile",
        json={
            "name": "service-recovery",
            "description": "Diagnose and recover the edge service.",
            "triggers": ["backend unavailable"],
        },
    )
    assert compiled.status_code == 201
    skill_id = compiled.json()["skill_id"]
    parent_id = compiled.json()["version_id"]

    child = SkillVersion(
        id="ver_child",
        skill_id=skill_id,
        version="0.2.0",
        parent_version_id=parent_id,
        status=SkillVersionStatus.CANDIDATE,
        artifact_path=None,
        manifest_hash=None,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    with connection(tmp_path / "api.sqlite") as conn:
        insert_skill_version(conn, child)

    versions = client.get(f"/api/skills/{skill_id}/versions")
    assert versions.status_code == 200
    by_id = {row["id"]: row for row in versions.json()}
    assert by_id[parent_id]["parent_version_id"] is None
    assert by_id["ver_child"]["parent_version_id"] == parent_id


def test_read_skill_version_file_happy_path(tmp_path: Path) -> None:
    client, gateway = _client(tmp_path)
    client.app.dependency_overrides[get_compile_gateway] = lambda: gateway
    compiled = client.post(
        f"/api/projects/{_PROJECT}/skills/compile",
        json={
            "name": "service-recovery",
            "description": "Diagnose and recover the edge service.",
            "triggers": ["backend unavailable"],
        },
    )
    assert compiled.status_code == 201
    skill_id = compiled.json()["skill_id"]
    version_id = compiled.json()["version_id"]

    response = client.get(
        f"/api/skills/{skill_id}/versions/{version_id}/file",
        params={"path": "SKILL.md"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == "SKILL.md"
    assert payload["text"].startswith("---")
    assert "service-recovery" in payload["text"]


def test_read_skill_version_file_rejects_path_traversal(tmp_path: Path) -> None:
    client, gateway = _client(tmp_path)
    client.app.dependency_overrides[get_compile_gateway] = lambda: gateway
    compiled = client.post(
        f"/api/projects/{_PROJECT}/skills/compile",
        json={
            "name": "service-recovery",
            "description": "Diagnose and recover the edge service.",
            "triggers": ["backend unavailable"],
        },
    )
    assert compiled.status_code == 201
    skill_id = compiled.json()["skill_id"]
    version_id = compiled.json()["version_id"]

    blocked = client.get(
        f"/api/skills/{skill_id}/versions/{version_id}/file",
        params={"path": "../SKILL.md"},
    )
    assert blocked.status_code == 400
    assert blocked.json()["error"]["message"] == "invalid path"

    absolute = client.get(
        f"/api/skills/{skill_id}/versions/{version_id}/file",
        params={"path": "/etc/passwd"},
    )
    assert absolute.status_code == 400


def test_unknown_project_and_skill_are_not_found(tmp_path: Path) -> None:
    client, _gateway = _client(tmp_path)
    missing = client.post(
        "/api/projects/missing/skills/compile",
        json={
            "name": "service-recovery",
            "description": "Diagnose and recover the edge service.",
            "triggers": ["backend unavailable"],
        },
    )
    assert missing.status_code == 404
    assert client.post("/api/skills/missing/validate").status_code == 404
    assert (
        client.get(
            "/api/skills/missing/versions/missing/file",
            params={"path": "SKILL.md"},
        ).status_code
        == 404
    )


def test_list_skills_empty_db_returns_empty_list(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite"
    initialize_database(db_path)
    settings = Settings(_env_file=None, sqlite_path=db_path)
    client = TestClient(create_app(settings, bus=EventBus()))
    response = client.get("/api/skills")
    assert response.status_code == 200
    assert response.json() == []


def test_list_skills_returns_inserted_skill(tmp_path: Path) -> None:
    client, _gateway = _client(tmp_path)
    db_path = tmp_path / "api.sqlite"
    with connection(db_path) as conn:
        insert_skill(
            conn,
            Skill(
                id="skill_list_1",
                project_id=_PROJECT,
                name="service-recovery",
                description="Recover edge services.",
                current_version_id=None,
            ),
        )

    response = client.get("/api/skills")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0] == {
        "id": "skill_list_1",
        "project_id": _PROJECT,
        "name": "service-recovery",
        "description": "Recover edge services.",
        "current_version_id": None,
    }


def _client(tmp_path: Path) -> tuple[TestClient, ModelGateway]:
    db_path = tmp_path / "api.sqlite"
    initialize_database(db_path)
    _seed(db_path)
    settings = Settings(
        _env_file=None,
        sqlite_path=db_path,
        data_dir=tmp_path / "data",
        skills_generated_dir=tmp_path / "generated",
        retrieval_backend="memory",
    )
    gateway = ModelGateway(
        FakeModelAdapter([_spec(), _instructions(), _scripts(), _evals()]),
        settings=settings,
        sink=SqliteTraceSink(db_path),
        bus=EventBus(),
    )
    return TestClient(create_app(settings, bus=EventBus())), gateway


def _seed(db_path: Path) -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id=_PROJECT, name="lab", created_at=created))
        insert_source_document(
            conn,
            SourceDocument(
                id=_DOCUMENT,
                project_id=_PROJECT,
                filename="runbook.md",
                sha256="abc123",
                version="1",
                parser="markdown",
                created_at=created,
            ),
        )
        insert_knowledge_unit(
            conn,
            KnowledgeUnit(
                id=_UNIT,
                document_id=_DOCUMENT,
                type=KnowledgeUnitType.PROCEDURE,
                content={
                    "title": "Service Down",
                    "trigger": "backend unavailable",
                    "steps": ["Inspect the backend."],
                    "success_criteria": ["HTTP 200 from the health check."],
                    "source_refs": [
                        {
                            "document_id": _DOCUMENT,
                            "chunk_id": "chunk_down",
                            "page": None,
                            "line_start": 4,
                            "line_end": 8,
                        },
                    ],
                },
            ),
        )


def _response(payload: dict[str, object]) -> ModelResponse:
    return ModelResponse(content=json.dumps(payload))


def _spec() -> ModelResponse:
    return _response(
        {
            "name": "service-recovery",
            "description": "Diagnose and recover the edge service.",
            "triggers": ["backend unavailable"],
            "tools": ["docker.inspect", "http.get"],
            "permissions": {
                "filesystem": {"read": ["/workspace"], "write": ["/workspace/runtime"]},
                "network": {"allow": ["localhost"]},
                "shell": {"destructive_commands": False},
            },
            "success": ["HTTP 200 from the health check."],
            "sources": [_DOCUMENT],
        },
    )


def _instructions() -> ModelResponse:
    return _response(
        {
            "instructions": [
                {
                    "knowledge_unit_id": _UNIT,
                    "text": "Inspect the backend.",
                    "kind": "procedure",
                },
            ],
        },
    )


def _scripts() -> ModelResponse:
    return _response(
        {
            "calls": [
                {"function": "docker_inspect", "service": "backend"},
                {"function": "http_get"},
            ],
        },
    )


def _evals() -> ModelResponse:
    return _response(
        {
            "cases": [
                {
                    "id": "eval_backend_stopped",
                    "name": "backend process stopped",
                    "task": "Restore the service.",
                    "fixture": "backend_stopped",
                },
            ],
        },
    )
