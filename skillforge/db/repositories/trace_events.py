"""Trace event persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType


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


def list_trace_events_by_run(conn: sqlite3.Connection, run_id: str) -> list[TraceEvent]:
    rows = conn.execute(
        """
        SELECT id, run_id, type, timestamp, payload
        FROM trace_events
        WHERE run_id = ?
        ORDER BY timestamp ASC, id ASC
        """,
        (run_id,),
    ).fetchall()
    return [_event_from_row(row) for row in rows]


def _event_from_row(row: sqlite3.Row | tuple[Any, ...]) -> TraceEvent:
    payload = json.loads(row[4]) if row[4] else {}
    if not isinstance(payload, dict):
        payload = {}
    return TraceEvent(
        id=row[0],
        run_id=row[1],
        type=TraceEventType(row[2]),
        timestamp=datetime.fromisoformat(row[3]),
        stage=payload.get("stage"),
        name=payload.get("name"),
        input=payload.get("input") or {},
        output=payload.get("output") or {},
        duration_ms=payload.get("duration_ms"),
    )
