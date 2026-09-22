"""Read stored harness runs and their trace events."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from skillforge.api.deps import get_settings_dep
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.repositories.agent_runs import AgentRunRecord, get_agent_run
from skillforge.db.repositories.trace_events import list_trace_events_by_run
from skillforge.domain.entities import TraceEvent

router = APIRouter(prefix="/runs", tags=["runs"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    final_content: str | None
    steps: int
    tool_errors: int
    tokens: int
    latency_ms: int
    policy_violations: int


class RunEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    type: str
    timestamp: datetime
    stage: str | None
    name: str | None
    input: dict
    output: dict
    duration_ms: int | None


def _run_response(record: AgentRunRecord) -> RunResponse:
    return RunResponse(
        id=record.id,
        status=record.status,
        final_content=record.final_content,
        steps=record.steps,
        tool_errors=record.tool_errors,
        tokens=record.tokens,
        latency_ms=record.latency_ms,
        policy_violations=record.policy_violations,
    )


def _event_response(event: TraceEvent) -> RunEventResponse:
    return RunEventResponse(
        id=event.id,
        run_id=event.run_id,
        type=event.type.value,
        timestamp=event.timestamp,
        stage=event.stage,
        name=event.name,
        input=event.input,
        output=event.output,
        duration_ms=event.duration_ms,
    )


def _load_run(db_path: Path, run_id: str) -> AgentRunRecord | None:
    with connection(db_path) as conn:
        return get_agent_run(conn, run_id)


def _load_events(db_path: Path, run_id: str) -> list[TraceEvent]:
    with connection(db_path) as conn:
        return list_trace_events_by_run(conn, run_id)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, settings: SettingsDep) -> RunResponse:
    record = await asyncio.to_thread(_load_run, settings.sqlite_path, run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_response(record)


@router.get("/{run_id}/events", response_model=list[RunEventResponse])
async def get_run_events(run_id: str, settings: SettingsDep) -> list[RunEventResponse]:
    record = await asyncio.to_thread(_load_run, settings.sqlite_path, run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    events = await asyncio.to_thread(_load_events, settings.sqlite_path, run_id)
    return [_event_response(event) for event in events]
