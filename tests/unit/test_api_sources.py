"""C5.7: source upload, extract, search, and index rebuild."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from starlette.testclient import TestClient

from skillforge.api.main import create_app
from skillforge.api.routers.sources import get_gateway
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.projects import insert_project
from skillforge.domain.entities import Project, TraceEvent
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.tracing.bus import EventBus

_MARKDOWN = b"# Title\n\nbody\n"
_UNIT = {
    "units": [
        {
            "type": "procedure",
            "title": "Recover backend service",
            "trigger": "HTTP 502",
            "steps": ["inspect backend"],
            "confidence": 0.8,
        }
    ]
}


def test_upload_extract_search_and_rebuild(tmp_path: Path) -> None:
    client, db_path = _client(tmp_path)
    _seed(db_path)
    with client:
        uploaded = client.post(
            "/api/projects/proj_1/sources",
            files={"file": ("notes.md", _MARKDOWN, "text/markdown")},
        )
        assert uploaded.status_code == 201
        assert uploaded.json()["parser"] == "markdown"
        listed = client.get("/api/projects/proj_1/sources")
        assert listed.status_code == 200
        assert listed.json()[0]["filename"] == "notes.md"

        extracted = client.post("/api/projects/proj_1/extract")
        assert extracted.status_code == 200
        assert extracted.json()[0]["title"] == "Recover backend service"

        knowledge = client.get("/api/projects/proj_1/knowledge")
        assert knowledge.status_code == 200
        assert knowledge.json()[0]["type"] == "procedure"

        found = client.get("/api/projects/proj_1/knowledge/search", params={"q": "Title"})
        assert found.status_code == 200
        body = found.json()
        assert body["backend"] == "sqlite_fts"
        assert body["mode_used"] == "keyword"
        assert body["hits"]

        rebuilt = client.post("/api/projects/proj_1/index/rebuild")
        assert rebuilt.status_code == 200
        assert rebuilt.json() == {"project_id": "proj_1", "status": "rebuilt"}


def test_unknown_project_and_empty_query(tmp_path: Path) -> None:
    client, _db = _client(tmp_path)
    with client:
        missing = client.post(
            "/api/projects/missing/sources",
            files={"file": ("notes.md", _MARKDOWN, "text/markdown")},
        )
        assert missing.status_code == 404
        empty = client.get("/api/projects/proj_1/knowledge/search", params={"q": ""})
        assert empty.status_code == 422


class _ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    db_path = tmp_path / "api.sqlite"
    initialize_database(db_path)
    settings = Settings(
        _env_file=None,
        sqlite_path=db_path,
        data_dir=tmp_path / "data",
    )
    app = create_app(settings, bus=EventBus())

    def _gateway() -> ModelGateway:
        return ModelGateway(
            FakeModelAdapter([ModelResponse(content=json.dumps(_UNIT))]),
            settings=settings,
            sink=_ListSink(),
            bus=EventBus(),
        )

    app.dependency_overrides[get_gateway] = _gateway
    return TestClient(app), db_path


def _seed(db_path: Path) -> None:
    with connection(db_path) as conn:
        insert_project(
            conn,
            Project(id="proj_1", name="lab", created_at=datetime.now(UTC)),
        )
