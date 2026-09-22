"""C5.9: the service recovery runbook yields a separate Appendix B rule."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.chunks import list_chunks_by_document
from skillforge.db.repositories.projects import insert_project
from skillforge.domain.entities import Chunk, Project, TraceEvent
from skillforge.domain.enums import KnowledgeUnitType
from skillforge.ingestion.chunking import chunk_document
from skillforge.ingestion.store import store_upload
from skillforge.ingestion.text import parse_stored
from skillforge.knowledge.extractor import extract_document
from skillforge.knowledge.retrieval.backends.memory import MemoryIndex
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.tracing.bus import EventBus

_REPO = Path(__file__).resolve().parents[3]
_RUNBOOK = _REPO / "demo" / "docs" / "service-recovery-runbook.md"
_FIXTURE = _REPO / "tests" / "fixtures" / "retrieval" / "runbook_index.json"
_TITLES = (
    "Service Recovery Runbook",
    "Service Down",
    "502 from proxy",
    "Appendix B: Reverse Proxy Troubleshooting",
)
_APPENDIX_TRIGGER = "nginx reload failed / upstream mismatch"
_APPENDIX_STEPS = [
    "Run nginx -t before any nginx reload.",
    "Compare the upstream port with the backend listen port.",
    "Remove this_is_not_valid_nginx;.",
]


def test_extract_runbook_keeps_appendix_b_separate(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    root = tmp_path / "sources"
    settings = Settings(
        _env_file=None,
        sqlite_path=db_path,
        data_dir=tmp_path / "data",
        retrieval_backend="memory",
    )
    _seed(db_path)
    document = store_upload(
        db_path,
        "proj_runbook",
        "service-recovery-runbook.md",
        _RUNBOOK.read_bytes(),
        root=root,
    )
    parsed = parse_stored(document, root)
    chunk_document(db_path, document, parsed, settings=settings)
    with connection(db_path) as conn:
        chunks = list_chunks_by_document(conn, document.id)
    assert [chunk.title for chunk in chunks] == list(_TITLES)

    units = asyncio.run(
        extract_document(
            db_path,
            document.id,
            _gateway(),
            index=MemoryIndex(),
        )
    )
    by_title = {str(unit.content["title"]): unit for unit in units}
    assert set(by_title) == set(_TITLES[1:])
    service_down = by_title["Service Down"]
    proxy = by_title["502 from proxy"]
    appendix = by_title["Appendix B: Reverse Proxy Troubleshooting"]
    assert service_down.type is KnowledgeUnitType.PROCEDURE
    assert service_down.content["trigger"] == "backend unavailable"
    assert proxy.type is KnowledgeUnitType.PROCEDURE
    assert proxy.content["trigger"] == "HTTP 502 from reverse proxy"
    assert appendix.type is KnowledgeUnitType.DIAGNOSTIC_RULE
    assert appendix.content["trigger"] == _APPENDIX_TRIGGER
    assert appendix.content["steps"] == _APPENDIX_STEPS
    refs = appendix.content["source_refs"]
    assert len(refs) == 1
    appendix_chunk = chunks[-1]
    assert refs[0]["chunk_id"] == appendix_chunk.id
    assert refs[0]["line_start"] == appendix_chunk.line_start
    assert refs[0]["line_end"] == appendix_chunk.line_end


def test_runbook_index_matches_chunker(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    root = tmp_path / "sources"
    settings = Settings(
        _env_file=None,
        sqlite_path=db_path,
        data_dir=tmp_path / "data",
        retrieval_backend="memory",
    )
    _seed(db_path)
    document = store_upload(
        db_path,
        "proj_runbook",
        "service-recovery-runbook.md",
        _RUNBOOK.read_bytes(),
        root=root,
    )
    chunk_document(db_path, document, parse_stored(document, root), settings=settings)
    with connection(db_path) as conn:
        chunks = list_chunks_by_document(conn, document.id)
    fixture_chunks = [
        row for row in json.loads(_FIXTURE.read_text(encoding="utf-8")) if row["kind"] == "chunk"
    ]
    assert len(fixture_chunks) == len(chunks)
    for row, chunk in zip(fixture_chunks, chunks, strict=True):
        assert _chunk_view(row) == _chunk_view(chunk)


def _chunk_view(item: dict[str, object] | Chunk) -> tuple[object, ...]:
    if isinstance(item, Chunk):
        return (item.title, item.text, item.line_start, item.line_end)
    return (item["title"], item["text"], item["line_start"], item["line_end"])


def _gateway() -> ModelGateway:
    payloads = [
        {"units": []},
        {
            "units": [
                {
                    "type": "procedure",
                    "title": "Service Down",
                    "trigger": "backend unavailable",
                    "steps": ["docker.restart the service named backend"],
                    "confidence": 0.9,
                }
            ]
        },
        {
            "units": [
                {
                    "type": "procedure",
                    "title": "502 from proxy",
                    "trigger": "HTTP 502 from reverse proxy",
                    "steps": ["replace the upstream line with server backend:8080;"],
                    "confidence": 0.9,
                }
            ]
        },
        {
            "units": [
                {
                    "type": "diagnostic_rule",
                    "title": "Appendix B: Reverse Proxy Troubleshooting",
                    "trigger": _APPENDIX_TRIGGER,
                    "steps": _APPENDIX_STEPS,
                    "confidence": 0.86,
                }
            ]
        },
    ]
    return ModelGateway(
        FakeModelAdapter([ModelResponse(content=json.dumps(item)) for item in payloads]),
        settings=Settings(_env_file=None),
        sink=_ListSink(),
        bus=EventBus(),
    )


def _seed(db_path: Path) -> None:
    initialize_database(db_path)
    with connection(db_path) as conn:
        insert_project(
            conn,
            Project(id="proj_runbook", name="lab", created_at=datetime.now(UTC)),
        )


class _ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)
