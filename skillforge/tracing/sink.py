"""Trace persistence sinks."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from skillforge.config import get_settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.trace_events import insert_trace_event
from skillforge.domain.entities import TraceEvent


class TraceSink(Protocol):
    async def write(self, event: TraceEvent) -> None: ...


class SqliteTraceSink:
    """Persists trace events to the system-of-record SQLite database."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path if db_path is not None else get_settings().sqlite_path
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            initialize_database(self._db_path)
            self._initialized = True

    async def write(self, event: TraceEvent) -> None:
        self._ensure_initialized()
        with connection(self._db_path) as conn:
            insert_trace_event(conn, event)
