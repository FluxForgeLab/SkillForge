"""C5.4: retrieval contract. Every backend in the list must pass."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.chunks import insert_chunks
from skillforge.db.repositories.knowledge_units import insert_knowledge_unit
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.source_documents import insert_source_document
from skillforge.domain.entities import Chunk, KnowledgeUnit, Project, SourceDocument, TraceEvent
from skillforge.domain.enums import KnowledgeUnitType, TraceEventType
from skillforge.knowledge.retrieval.backends.memory import MemoryIndex
from skillforge.knowledge.retrieval.base import IndexDocument, RetrievalQuery
from skillforge.knowledge.retrieval.embedder import NullEmbedder
from skillforge.knowledge.retrieval.indexer import Indexer
from skillforge.knowledge.retrieval.retriever import Retriever

pytestmark = pytest.mark.parametrize("backend", ["memory"], indirect=True)


@pytest.fixture
def backend(request: pytest.FixtureRequest) -> MemoryIndex:
    if request.param == "memory":
        return MemoryIndex()
    raise AssertionError(f"unknown backend {request.param}")


async def test_upsert_search_returns_expected_top_hit(backend: MemoryIndex) -> None:
    docs = [_doc(id=f"c{i}", text=f"filler {i}") for i in range(4)]
    docs.append(_doc(id="target", text="unique-marker sits here"))
    await backend.upsert(docs)
    hits = await backend.search(_query("unique-marker"))
    assert hits[0].id == "target"


async def test_project_isolation(backend: MemoryIndex) -> None:
    await backend.upsert(
        [
            _doc(id="a", project_id="proj_a", text="shared-term"),
            _doc(id="b", project_id="proj_b", text="shared-term"),
        ]
    )
    hits = await backend.search(_query("shared-term", project_id="proj_a"))
    assert [hit.id for hit in hits] == ["a"]


async def test_kind_filter_excludes_chunks(backend: MemoryIndex) -> None:
    await backend.upsert(
        [
            _doc(id="chunk_1", kind="chunk", text="shared-kind"),
            _doc(id="ku_1", kind="knowledge_unit", type="procedure", text="shared-kind"),
        ]
    )
    hits = await backend.search(_query("shared-kind", kinds=("knowledge_unit",)))
    assert [hit.id for hit in hits] == ["ku_1"]


async def test_type_filter_keeps_diagnostic_rules(backend: MemoryIndex) -> None:
    await backend.upsert(
        [
            _doc(id="rule", kind="knowledge_unit", type="diagnostic_rule", text="rule-body"),
            _doc(id="proc", kind="knowledge_unit", type="procedure", text="rule-body"),
            _doc(id="chunk_1", kind="chunk", text="rule-body"),
        ]
    )
    hits = await backend.search(_query("rule-body", type="diagnostic_rule"))
    assert [hit.id for hit in hits] == ["rule"]


async def test_document_id_filter(backend: MemoryIndex) -> None:
    await backend.upsert(
        [
            _doc(id="a", document_id="doc_a", text="scoped-word"),
            _doc(id="b", document_id="doc_b", text="scoped-word"),
        ]
    )
    hits = await backend.search(_query("scoped-word", document_ids=("doc_a",)))
    assert [hit.id for hit in hits] == ["a"]


async def test_upsert_same_id_does_not_duplicate(backend: MemoryIndex) -> None:
    await backend.upsert([_doc(id="once", text="once-token")])
    await backend.upsert([_doc(id="once", text="once-token")])
    hits = await backend.search(_query("once-token"))
    assert [hit.id for hit in hits] == ["once"]


async def test_delete_document_leaves_others(backend: MemoryIndex) -> None:
    await backend.upsert(
        [
            _doc(id="gone", document_id="doc_1", text="delete-me"),
            _doc(id="stay", document_id="doc_2", text="delete-me"),
        ]
    )
    await backend.delete(project_id="proj", document_id="doc_1")
    hits = await backend.search(_query("delete-me"))
    assert [hit.id for hit in hits] == ["stay"]


async def test_scores_are_unit_interval_and_descending(backend: MemoryIndex) -> None:
    await backend.upsert(
        [
            _doc(id="partial", text="alpha"),
            _doc(id="full", text="alpha beta"),
        ]
    )
    hits = await backend.search(_query("alpha beta"))
    assert [hit.id for hit in hits] == ["full", "partial"]
    scores = [hit.score for hit in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= score <= 1 for score in scores)


async def test_hybrid_request_degrades_to_keyword(backend: MemoryIndex) -> None:
    await backend.upsert([_doc(id="kw", text="degrade-token")])
    hits = await backend.search(_query("degrade-token", mode="hybrid"))
    assert hits[0].mode_used == "keyword"
    assert hits[0].backend == "memory"


async def test_rebuild_is_idempotent(backend: MemoryIndex, tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    _seed_corpus(db_path)
    indexer = Indexer(db_path, backend)
    await indexer.rebuild("proj")
    first = await backend.search(_query("rebuild-alpha"))
    await indexer.rebuild("proj")
    second = await backend.search(_query("rebuild-alpha"))
    assert [(hit.id, hit.score) for hit in first] == [(hit.id, hit.score) for hit in second]
    assert first[0].id == "chunk_a"
    rules = await backend.search(_query("rebuild-rule", type="diagnostic_rule"))
    assert [hit.id for hit in rules] == ["ku_1"]


async def test_retriever_emits_retrieval_query(backend: MemoryIndex) -> None:
    await backend.upsert([_doc(id="emit_1", text="emit-token")])
    sink = _ListSink()
    retriever = Retriever(
        index=backend,
        embedder=NullEmbedder(),
        settings=Settings(_env_file=None),
        sink=sink,
    )
    hits = await retriever.search("emit-token", "proj", k=5)
    assert [hit.id for hit in hits] == ["emit_1"]
    event = sink.events[-1]
    assert event.type is TraceEventType.RETRIEVAL_QUERY
    assert event.output["backend"] == "memory"
    assert event.output["mode_used"] == "keyword"
    assert event.output["k"] == 5
    assert event.output["query_len"] == len("emit-token")
    assert event.output["hit_ids"] == ["emit_1"]


class _ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


def _doc(**overrides: object) -> IndexDocument:
    fields: dict[str, object] = {
        "id": "c1",
        "kind": "chunk",
        "project_id": "proj",
        "document_id": "doc",
        "text": "alpha",
    }
    fields.update(overrides)
    return IndexDocument.model_validate(fields)


def _query(text: str, **overrides: object) -> RetrievalQuery:
    fields: dict[str, object] = {"text": text, "project_id": "proj"}
    fields.update(overrides)
    return RetrievalQuery.model_validate(fields)


def _seed_corpus(db_path: Path) -> None:
    initialize_database(db_path)
    now = datetime.now(UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id="proj", name="lab", created_at=now))
        insert_source_document(
            conn,
            SourceDocument(
                id="doc_1",
                project_id="proj",
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
                    project_id="proj",
                    ordinal=0,
                    text="rebuild-alpha",
                ),
                Chunk(
                    id="chunk_b",
                    document_id="doc_1",
                    project_id="proj",
                    ordinal=1,
                    text="rebuild-beta",
                ),
            ],
        )
        insert_knowledge_unit(
            conn,
            KnowledgeUnit(
                id="ku_1",
                document_id="doc_1",
                type=KnowledgeUnitType.DIAGNOSTIC_RULE,
                content={"text": "rebuild-rule", "title": "Appendix B"},
                source_location={"page": 2, "line_start": 10, "line_end": 12},
            ),
        )
