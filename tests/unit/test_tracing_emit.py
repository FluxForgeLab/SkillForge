"""C2.3: Trace emit, bus, and sqlite sink."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillforge.db import connect, initialize_database
from skillforge.domain.enums import TraceEventType
from skillforge.tracing import EventBus, SqliteTraceSink, emit


@pytest.mark.asyncio
async def test_emit_notifies_subscriber(tmp_path: Path) -> None:
    bus = EventBus()
    received: list[str] = []

    async def handler(event) -> None:
        received.append(event.id)

    bus.subscribe(handler)
    event = await emit(
        "run_sub",
        TraceEventType.TOOL_CALL,
        name="docker.inspect",
        input={"container": "backend"},
        bus=bus,
        sink=SqliteTraceSink(tmp_path / "sub.db"),
    )
    assert received == [event.id]


@pytest.mark.asyncio
async def test_emit_persists_to_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "trace.db"
    initialize_database(db_path)
    sink = SqliteTraceSink(db_path)

    await emit(
        "run_db",
        TraceEventType.MODEL_REQUEST,
        name="generate",
        input={"prompt_len": 12},
        output={"tokens": 3},
        duration_ms=42,
        stage="runtime",
        bus=EventBus(),
        sink=sink,
    )

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, run_id, type, timestamp, payload FROM trace_events",
        ).fetchone()
        assert row is not None
        _id, run_id, type_, _timestamp, payload_raw = row
        assert run_id == "run_db"
        assert type_ == "model_request"
        payload = json.loads(payload_raw)
        assert payload["stage"] == "runtime"
        assert payload["name"] == "generate"
        assert payload["input"] == {"prompt_len": 12}
        assert payload["output"] == {"tokens": 3}
        assert payload["duration_ms"] == 42
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_emit_end_to_end(tmp_path: Path) -> None:
    db_path = tmp_path / "e2e.db"
    bus = EventBus()
    sink = SqliteTraceSink(db_path)
    seen: list[TraceEventType] = []

    async def handler(event) -> None:
        seen.append(event.type)

    bus.subscribe(handler)
    await emit(
        "run_e2e",
        TraceEventType.WORKFLOW_STARTED,
        name="pipeline",
        bus=bus,
        sink=sink,
    )

    assert seen == [TraceEventType.WORKFLOW_STARTED]
    conn = connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
        assert count == 1
    finally:
        conn.close()
