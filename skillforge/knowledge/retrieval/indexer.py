"""Project SQLite rows into a RetrievalIndex. The index can be rebuilt from scratch."""

from __future__ import annotations

import json
from pathlib import Path

from skillforge.db.connection import connection
from skillforge.db.repositories.chunks import list_chunks_by_document, list_chunks_by_project
from skillforge.db.repositories.knowledge_units import (
    list_knowledge_units_by_document,
    list_knowledge_units_by_project,
)
from skillforge.db.repositories.source_documents import get_source_document
from skillforge.domain.entities import Chunk, KnowledgeUnit
from skillforge.knowledge.retrieval.base import IndexDocument, RetrievalIndex


class Indexer:
    """Read the system of record and upsert a disposable projection."""

    def __init__(self, db_path: Path, index: RetrievalIndex) -> None:
        self._db_path = db_path
        self._index = index

    async def index_document(self, document_id: str) -> None:
        """Project the chunks of one document. Knowledge units stay untouched."""
        await self._index.ensure_schema()
        with connection(self._db_path) as conn:
            chunks = list_chunks_by_document(conn, document_id)
        if chunks:
            await self._index.upsert([_chunk_document(chunk) for chunk in chunks])

    async def index_knowledge_units(self, document_id: str) -> None:
        """Project the knowledge units of one document."""
        await self._index.ensure_schema()
        with connection(self._db_path) as conn:
            units = list_knowledge_units_by_document(conn, document_id)
            source = get_source_document(conn, document_id)
        if source is None or not units:
            return
        await self._index.upsert(
            [_unit_document(unit, project_id=source.project_id) for unit in units]
        )

    async def rebuild(self, project_id: str) -> None:
        """Drop the project's projection and load every chunk and knowledge unit again."""
        await self._index.ensure_schema()
        await self._index.delete(project_id=project_id)
        with connection(self._db_path) as conn:
            chunks = list_chunks_by_project(conn, project_id)
            units = list_knowledge_units_by_project(conn, project_id)
        docs = [_chunk_document(chunk) for chunk in chunks]
        docs.extend(_unit_document(unit, project_id=project_id) for unit in units)
        if docs:
            await self._index.upsert(docs)


def _chunk_document(chunk: Chunk) -> IndexDocument:
    return IndexDocument(
        id=chunk.id,
        kind="chunk",
        project_id=chunk.project_id,
        document_id=chunk.document_id,
        text=chunk.text,
        title=chunk.title,
        page=chunk.page,
        line_start=chunk.line_start,
        line_end=chunk.line_end,
    )


def _unit_document(unit: KnowledgeUnit, *, project_id: str) -> IndexDocument:
    location = unit.source_location or {}
    return IndexDocument(
        id=unit.id,
        kind="knowledge_unit",
        project_id=project_id,
        document_id=unit.document_id,
        text=_unit_text(unit.content),
        title=_unit_title(unit.content),
        type=unit.type.value,
        page=_loc_int(location, "page"),
        line_start=_loc_int(location, "line_start"),
        line_end=_loc_int(location, "line_end"),
    )


def _unit_text(content: dict[str, object]) -> str:
    text = content.get("text")
    if isinstance(text, str):
        return text
    return json.dumps(content, sort_keys=True, ensure_ascii=False)


def _unit_title(content: dict[str, object]) -> str | None:
    title = content.get("title")
    return title if isinstance(title, str) else None


def _loc_int(location: dict[str, object], key: str) -> int | None:
    value = location.get(key)
    return value if isinstance(value, int) else None
