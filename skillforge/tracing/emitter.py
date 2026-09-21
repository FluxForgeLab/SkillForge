"""TraceEvent emission: persist then broadcast."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import SqliteTraceSink, TraceSink

_DEFAULT_BUS = EventBus()
_DEFAULT_SINK = SqliteTraceSink()


@lru_cache(maxsize=1)
def get_bus() -> EventBus:
    return _DEFAULT_BUS


def get_default_sink() -> SqliteTraceSink:
    return _DEFAULT_SINK


def _coerce_event_type(type: TraceEventType | str) -> TraceEventType:
    if isinstance(type, TraceEventType):
        return type
    return TraceEventType(type)


async def emit(
    run_id: str,
    type: TraceEventType | str,
    name: str | None = None,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    *,
    stage: str | None = None,
    bus: EventBus | None = None,
    sink: TraceSink | None = None,
) -> TraceEvent:
    """Record a trace event to SQLite, then notify in-process subscribers."""
    event_type = _coerce_event_type(type)
    event = TraceEvent(
        id=f"evt_{uuid4().hex}",
        run_id=run_id,
        type=event_type,
        timestamp=datetime.now(UTC),
        stage=stage,
        name=name,
        input=input or {},
        output=output or {},
        duration_ms=duration_ms,
    )
    target_sink = sink if sink is not None else get_default_sink()
    target_bus = bus if bus is not None else get_bus()
    await target_sink.write(event)
    await target_bus.publish(event)
    return event
