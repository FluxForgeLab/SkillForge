"""C2.1: SQLite schema and idempotent initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from skillforge.db import connect, initialize_database, load_schema_sql

EXPECTED_TABLES = frozenset(
    {
        "projects",
        "source_documents",
        "chunks",
        "knowledge_units",
        "skills",
        "skill_versions",
        "eval_cases",
        "evaluation_runs",
        "eval_seals",
        "eval_cache",
        "trace_events",
        "agent_runs",
    }
)


def test_initialize_database_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "skillforge.db"
    initialize_database(db_path)
    initialize_database(db_path)


def test_schema_sql_has_no_fts5() -> None:
    assert "fts5" not in load_schema_sql().lower()


def test_foreign_keys_enforced(tmp_path: Path) -> None:
    db_path = tmp_path / "skillforge.db"
    initialize_database(db_path)
    conn = connect(db_path)
    try:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row is not None and row[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO source_documents (
                    id, project_id, filename, sha256, version, parser, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "doc_orphan",
                    "missing_project",
                    "x.pdf",
                    "abc",
                    "1",
                    "pypdf",
                    "2026-01-01T00:00:00Z",
                ),
            )
            conn.commit()
    finally:
        conn.close()


def test_expected_tables_exist(tmp_path: Path) -> None:
    db_path = tmp_path / "skillforge.db"
    initialize_database(db_path)
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        names = {row[0] for row in rows}
        assert EXPECTED_TABLES <= names
    finally:
        conn.close()
