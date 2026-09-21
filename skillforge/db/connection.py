"""SQLite connection helpers with WAL and foreign-key enforcement."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite database with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Context manager that commits on success and closes the connection."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
