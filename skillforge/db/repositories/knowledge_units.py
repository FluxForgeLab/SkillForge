"""Knowledge unit persistence. Indexing reads these rows; it does not own them."""

from __future__ import annotations

import json
import sqlite3

from skillforge.domain.entities import KnowledgeUnit
from skillforge.domain.enums import KnowledgeUnitType


def delete_knowledge_units_by_document(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute("DELETE FROM knowledge_units WHERE document_id = ?", (document_id,))


def insert_knowledge_unit(conn: sqlite3.Connection, unit: KnowledgeUnit) -> None:
    conn.execute(
        """
        INSERT INTO knowledge_units (
            id, document_id, type, content, source_location, confidence
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            unit.id,
            unit.document_id,
            unit.type.value,
            json.dumps(unit.content, sort_keys=True),
            json.dumps(unit.source_location, sort_keys=True) if unit.source_location else None,
            unit.confidence,
        ),
    )


def list_knowledge_units_by_document(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[KnowledgeUnit]:
    rows = conn.execute(
        """
        SELECT id, document_id, type, content, source_location, confidence
        FROM knowledge_units
        WHERE document_id = ?
        ORDER BY id ASC
        """,
        (document_id,),
    ).fetchall()
    return [_row(row) for row in rows]


def list_knowledge_units_by_project(
    conn: sqlite3.Connection,
    project_id: str,
) -> list[KnowledgeUnit]:
    rows = conn.execute(
        """
        SELECT ku.id, ku.document_id, ku.type, ku.content, ku.source_location, ku.confidence
        FROM knowledge_units ku
        JOIN source_documents sd ON sd.id = ku.document_id
        WHERE sd.project_id = ?
        ORDER BY ku.document_id ASC, ku.id ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row(row) for row in rows]


def _row(row: tuple[object, ...]) -> KnowledgeUnit:
    unit_id, document_id, unit_type, content, source_location, confidence = row
    location = json.loads(str(source_location)) if source_location is not None else None
    return KnowledgeUnit(
        id=str(unit_id),
        document_id=str(document_id),
        type=KnowledgeUnitType(str(unit_type)),
        content=json.loads(str(content)),
        source_location=location,
        confidence=float(confidence) if confidence is not None else None,
    )
