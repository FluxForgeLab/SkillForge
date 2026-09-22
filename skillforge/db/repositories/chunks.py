"""Chunk persistence. Retrieval indexes are a later projection."""

from __future__ import annotations

import sqlite3

from skillforge.domain.entities import Chunk


def insert_chunks(conn: sqlite3.Connection, chunks: list[Chunk]) -> None:
    conn.executemany(
        """
        INSERT INTO chunks (
            id, document_id, project_id, ordinal, text, title, page, line_start, line_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                chunk.id,
                chunk.document_id,
                chunk.project_id,
                chunk.ordinal,
                chunk.text,
                chunk.title,
                chunk.page,
                chunk.line_start,
                chunk.line_end,
            )
            for chunk in chunks
        ],
    )


def delete_chunks_by_document(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))


def list_chunks_by_project(conn: sqlite3.Connection, project_id: str) -> list[Chunk]:
    rows = conn.execute(
        """
        SELECT id, document_id, project_id, ordinal, text, title, page, line_start, line_end
        FROM chunks
        WHERE project_id = ?
        ORDER BY document_id ASC, ordinal ASC, id ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row(row) for row in rows]


def list_chunks_by_document(conn: sqlite3.Connection, document_id: str) -> list[Chunk]:
    rows = conn.execute(
        """
        SELECT id, document_id, project_id, ordinal, text, title, page, line_start, line_end
        FROM chunks
        WHERE document_id = ?
        ORDER BY ordinal ASC, id ASC
        """,
        (document_id,),
    ).fetchall()
    return [_row(row) for row in rows]


def _row(row: tuple[object, ...]) -> Chunk:
    (
        chunk_id,
        document_id,
        project_id,
        ordinal,
        text,
        title,
        page,
        line_start,
        line_end,
    ) = row
    return Chunk(
        id=str(chunk_id),
        document_id=str(document_id),
        project_id=str(project_id),
        ordinal=int(ordinal),
        text=str(text),
        title=str(title) if title is not None else None,
        page=int(page) if page is not None else None,
        line_start=int(line_start) if line_start is not None else None,
        line_end=int(line_end) if line_end is not None else None,
    )
