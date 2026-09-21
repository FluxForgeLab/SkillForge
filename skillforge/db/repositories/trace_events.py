"""Trace event persistence."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from skillforge.domain.entities import TraceEvent


def _payload_from_event(event: TraceEvent) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if event.stage is not None:
        payload["stage"] = event.stage
    if event.name is not None:
        payload["name"] = event.name
    if event.input:
        payload["input"] = event.input
    if event.output:
        payload["output"] = event.output
    if event.duration_ms is not None:
        payload["duration_ms"] = event.duration_ms
    return payload


def insert_trace_event(conn: sqlite3.Connection, event: TraceEvent) -> None:
    conn.execute(
        """
        INSERT INTO trace_events (id, run_id, type, timestamp, payload)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event.id,
            event.run_id,
            event.type.value,
            event.timestamp.isoformat(),
            json.dumps(_payload_from_event(event), ensure_ascii=False),
        ),
    )
