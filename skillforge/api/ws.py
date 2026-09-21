"""WebSocket broadcast for trace events."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from skillforge.domain.entities import TraceEvent

router = APIRouter()


def trace_event_to_wire(event: TraceEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


class ConnectionManager:
    """Tracks open WebSocket clients and broadcasts trace events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

    async def broadcast(self, event: TraceEvent) -> None:
        payload = trace_event_to_wire(event)
        async with self._lock:
            connections = list(self._connections)
        stale: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(payload)
            except Exception:
                stale.append(connection)
        if stale:
            async with self._lock:
                for connection in stale:
                    if connection in self._connections:
                        self._connections.remove(connection)


@router.websocket("/events")
async def events_websocket(websocket: WebSocket) -> None:
    manager: ConnectionManager = websocket.app.state.ws_manager
    await manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message.strip().lower() == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
