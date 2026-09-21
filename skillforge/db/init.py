"""Idempotent database initialization from packaged schema.sql."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from skillforge.config import get_settings
from skillforge.db.connection import connection


def load_schema_sql() -> str:
    schema = resources.files("skillforge.db").joinpath("schema.sql")
    return schema.read_text(encoding="utf-8")


def initialize_database(db_path: Path | None = None) -> None:
    """Create tables and indexes if they do not exist. Safe to call repeatedly."""
    path = db_path if db_path is not None else get_settings().sqlite_path
    path.parent.mkdir(parents=True, exist_ok=True)
    sql = load_schema_sql()
    with connection(path) as conn:
        conn.executescript(sql)
