"""Source document persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from skillforge.domain.entities import SourceDocument


def insert_source_document(conn: sqlite3.Connection, document: SourceDocument) -> None:
    conn.execute(
        """
        INSERT INTO source_documents (
            id, project_id, filename, sha256, version, parser, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document.id,
            document.project_id,
            document.filename,
            document.sha256,
            document.version,
            document.parser,
            document.created_at.isoformat(),
        ),
    )


def get_source_document(conn: sqlite3.Connection, document_id: str) -> SourceDocument | None:
    row = conn.execute(
        """
        SELECT id, project_id, filename, sha256, version, parser, created_at
        FROM source_documents
        WHERE id = ?
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        return None
    return _row(row)


def list_source_documents(conn: sqlite3.Connection, project_id: str) -> list[SourceDocument]:
    rows = conn.execute(
        """
        SELECT id, project_id, filename, sha256, version, parser, created_at
        FROM source_documents
        WHERE project_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row(row) for row in rows]


def list_source_documents_by_filename(
    conn: sqlite3.Connection,
    project_id: str,
    filename: str,
) -> list[SourceDocument]:
    rows = conn.execute(
        """
        SELECT id, project_id, filename, sha256, version, parser, created_at
        FROM source_documents
        WHERE project_id = ? AND filename = ?
        ORDER BY CAST(version AS INTEGER) ASC, id ASC
        """,
        (project_id, filename),
    ).fetchall()
    return [_row(row) for row in rows]


def _row(row: tuple[object, ...]) -> SourceDocument:
    document_id, project_id, filename, sha256, version, parser, created_at = row
    return SourceDocument(
        id=str(document_id),
        project_id=str(project_id),
        filename=str(filename),
        sha256=str(sha256),
        version=str(version),
        parser=str(parser),
        created_at=datetime.fromisoformat(str(created_at)),
    )
