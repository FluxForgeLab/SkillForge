"""C2.4: FastAPI health and WebSocket trace broadcast."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from skillforge.api.errors import register_exception_handlers
from skillforge.api.main import create_app
from skillforge.api.ws import ConnectionManager
from skillforge.config import Settings
from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.domain.errors import InvalidStateTransition
from skillforge.tracing import EventBus, SqliteTraceSink, emit


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


def test_health_ok() -> None:
    settings = Settings(_env_file=None)
    client = TestClient(create_app(settings))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "skillforge"}


def test_ws_ping_pong() -> None:
    settings = Settings(_env_file=None)
    with TestClient(create_app(settings)) as client:
        with client.websocket_connect("/api/events") as websocket:
            websocket.send_text("ping")
            assert websocket.receive_text() == "pong"


@pytest.mark.asyncio
async def test_emit_reaches_websocket_via_bus(tmp_path: Path) -> None:
    bus = EventBus()
    manager = ConnectionManager()
    fake = FakeWebSocket()
    await manager.connect(fake)

    async def forward(event: TraceEvent) -> None:
        await manager.broadcast(event)

    bus.subscribe(forward)
    await emit(
        "run_ws",
        TraceEventType.TOOL_CALL,
        name="file.read",
        input={"path": "/workspace/x"},
        bus=bus,
        sink=SqliteTraceSink(tmp_path / "api.db"),
    )
    assert len(fake.sent) == 1
    payload = fake.sent[0]
    assert payload["run_id"] == "run_ws"
    assert payload["type"] == "tool_call"
    assert payload["name"] == "file.read"
    assert payload["input"] == {"path": "/workspace/x"}


@pytest.mark.asyncio
async def test_connection_manager_broadcasts_to_multiple_clients() -> None:
    manager = ConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()
    await manager.connect(first)
    await manager.connect(second)
    event = TraceEvent(
        id="evt_test",
        run_id="run_multi",
        type=TraceEventType.WORKFLOW_STARTED,
        timestamp=datetime.now(UTC),
        name="pipeline",
    )
    await manager.broadcast(event)
    assert first.sent[0]["id"] == "evt_test"
    assert second.sent[0]["id"] == "evt_test"


def test_invalid_state_transition_error_shape() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise InvalidStateTransition(
            machine="skill_version",
            current="DRAFT",
            target="PUBLISHED",
        )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "invalid_state_transition"
    assert "DRAFT" in body["error"]["message"]


def test_http_exception_error_shape() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="Not found")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"
