"""SQLite FTS5 keyword index. The virtual table is created here, not in schema.sql."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from skillforge.db.connection import connection
from skillforge.knowledge.retrieval.base import (
    IndexDocument,
    IndexKind,
    RetrievalHit,
    RetrievalMode,
    RetrievalQuery,
)

_CREATE = """
CREATE VIRTUAL TABLE IF NOT EXISTS idx_fts_documents USING fts5(
    id UNINDEXED,
    kind UNINDEXED,
    project_id UNINDEXED,
    document_id UNINDEXED,
    type UNINDEXED,
    page UNINDEXED,
    line_start UNINDEXED,
    title,
    text,
    tokenize = 'unicode61 remove_diacritics 2'
)
"""


class SqliteFtsIndex:
    """Keyword search over ``idx_fts_documents``. Other modes degrade to keyword."""

    name = "sqlite_fts"
    capabilities: frozenset[RetrievalMode] = frozenset({"keyword"})

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def ensure_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with connection(self._db_path) as conn:
            conn.execute(_CREATE)

    async def upsert(self, docs: Sequence[IndexDocument]) -> None:
        await self.ensure_schema()
        with connection(self._db_path) as conn:
            for doc in docs:
                conn.execute("DELETE FROM idx_fts_documents WHERE id = ?", (doc.id,))
                conn.execute(
                    """
                    INSERT INTO idx_fts_documents (
                        id, kind, project_id, document_id, type, page, line_start, title, text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc.id,
                        doc.kind,
                        doc.project_id,
                        doc.document_id,
                        doc.type,
                        _cell(doc.page),
                        _cell(doc.line_start),
                        doc.title or "",
                        doc.text,
                    ),
                )

    async def delete(self, *, project_id: str, document_id: str | None = None) -> None:
        await self.ensure_schema()
        with connection(self._db_path) as conn:
            if document_id is None:
                conn.execute(
                    "DELETE FROM idx_fts_documents WHERE project_id = ?",
                    (project_id,),
                )
                return
            conn.execute(
                "DELETE FROM idx_fts_documents WHERE project_id = ? AND document_id = ?",
                (project_id, document_id),
            )

    async def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        await self.ensure_schema()
        match = _match_expr(query.text)
        if match is None or not query.kinds or query.document_ids == ():
            return []
        mode_used: RetrievalMode = query.mode if query.mode in self.capabilities else "keyword"
        sql, params = _search_sql(query, match)
        with connection(self._db_path) as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as exc:
                raise ValueError(f"fts query failed: {match}") from exc
        hits = [_hit(row, mode_used) for row in rows]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[: query.k]


def _cell(value: int | None) -> str:
    if value is None:
        return ""
    return str(value)


def _match_expr(text: str) -> str | None:
    parts: list[str] = []
    for raw in text.split():
        cleaned = raw.replace('"', "")
        if cleaned:
            parts.append(f'"{cleaned}"')
    if not parts:
        return None
    return " OR ".join(parts)


def _search_sql(query: RetrievalQuery, match: str) -> tuple[str, list[object]]:
    clauses = ["idx_fts_documents MATCH ?", "project_id = ?"]
    params: list[object] = [match, query.project_id]
    kind_marks = ", ".join("?" for _ in query.kinds)
    clauses.append(f"kind IN ({kind_marks})")
    params.extend(query.kinds)
    if query.type is not None:
        clauses.append("kind = 'knowledge_unit' AND type = ?")
        params.append(query.type)
    if query.document_ids is not None:
        marks = ", ".join("?" for _ in query.document_ids)
        clauses.append(f"document_id IN ({marks})")
        params.extend(query.document_ids)
    sql = f"""
        SELECT id, kind, document_id, type, page, line_start, title, text,
               bm25(idx_fts_documents) AS rank
        FROM idx_fts_documents
        WHERE {" AND ".join(clauses)}
    """
    return sql, params


def _hit(row: tuple[object, ...], mode_used: RetrievalMode) -> RetrievalHit:
    doc_id, kind, document_id, doc_type, page, line_start, title, text, rank = row
    magnitude = max(0.0, -float(rank))
    score = magnitude / (1.0 + magnitude)
    return RetrievalHit(
        id=str(doc_id),
        kind=cast(IndexKind, str(kind)),
        score=score,
        text=str(text or ""),
        title=str(title) if title else None,
        type=str(doc_type) if doc_type else None,
        document_id=str(document_id),
        page=_optional_int(page),
        line_start=_optional_int(line_start),
        backend="sqlite_fts",
        mode_used=mode_used,
    )


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value))
