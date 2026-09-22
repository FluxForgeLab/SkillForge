"""C5.6: FakeModel extraction merges units by title and indexes them."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.chunks import insert_chunks
from skillforge.db.repositories.knowledge_units import list_knowledge_units_by_document
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.source_documents import insert_source_document
from skillforge.domain.entities import Chunk, Project, SourceDocument, TraceEvent
from skillforge.knowledge.extractor import extract_document
from skillforge.knowledge.retrieval.backends.memory import MemoryIndex
from skillforge.knowledge.retrieval.base import RetrievalQuery
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.tracing.bus import EventBus

_SNAPSHOT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "knowledge" / "extraction_snapshot.json"
)

_FIRST = {
    "units": [
        {
            "type": "procedure",
            "title": "Recover backend service",
            "trigger": "HTTP 502",
            "steps": ["inspect backend", "restart backend"],
            "confidence": 0.8,
        }
    ]
}
_SECOND = {
    "units": [
        {
            "type": "procedure",
            "title": "recover backend service",
            "steps": ["restart backend", "verify health"],
            "confidence": 0.9,
        },
        {
            "type": "diagnostic_rule",
            "title": "Appendix B",
            "trigger": "nginx reload failed",
            "steps": ["run nginx -t"],
            "confidence": 0.7,
        },
    ]
}


async def test_extract_merges_titles_and_matches_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    _seed(db_path)
    sink = _ListSink()
    gateway = ModelGateway(
        FakeModelAdapter(
            [
                ModelResponse(content=json.dumps(_FIRST)),
                ModelResponse(content=json.dumps(_SECOND)),
            ]
        ),
        settings=Settings(_env_file=None),
        sink=sink,
        bus=EventBus(),
    )
    index = MemoryIndex()
    units = await extract_document(db_path, "doc_1", gateway, index=index)
    view = sorted(
        (
            {
                "type": unit.type.value,
                "title": unit.content["title"],
                "confidence": unit.confidence,
                "trigger": unit.content["trigger"],
                "steps": unit.content["steps"],
                "source_ref_count": len(unit.content["source_refs"]),
            }
            for unit in units
        ),
        key=lambda item: str(item["title"]),
    )
    expected = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    assert view == expected
    with connection(db_path) as conn:
        stored = list_knowledge_units_by_document(conn, "doc_1")
    assert len(stored) == 2
    hits = await index.search(RetrievalQuery(text="Recover", project_id="proj_1"))
    assert any(hit.title == "Recover backend service" for hit in hits)


class _ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


def _seed(db_path: Path) -> None:
    initialize_database(db_path)
    now = datetime.now(UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id="proj_1", name="lab", created_at=now))
        insert_source_document(
            conn,
            SourceDocument(
                id="doc_1",
                project_id="proj_1",
                filename="runbook.md",
                sha256="abc",
                version="1",
                parser="markdown",
                created_at=now,
            ),
        )
        insert_chunks(
            conn,
            [
                Chunk(
                    id="chunk_a",
                    document_id="doc_1",
                    project_id="proj_1",
                    ordinal=0,
                    text="Recover the backend.",
                    title="Service Down",
                    line_start=1,
                    line_end=3,
                ),
                Chunk(
                    id="chunk_b",
                    document_id="doc_1",
                    project_id="proj_1",
                    ordinal=1,
                    text="Appendix B: nginx -t.",
                    title="Appendix B",
                    line_start=10,
                    line_end=12,
                ),
            ],
        )
