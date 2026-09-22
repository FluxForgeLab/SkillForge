from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from starlette.testclient import TestClient

from skillforge.api.main import create_app
from skillforge.api.routers.demo import get_lab_inject, get_lab_reset
from skillforge.config import Settings
from skillforge.db import initialize_database
from skillforge.db.connection import connection
from skillforge.db.repositories.agent_runs import AgentRunRecord, insert_agent_run
from skillforge.db.repositories.trace_events import insert_trace_event
from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType


def _client(tmp_path: Path, inject, reset) -> tuple[TestClient, Path]:
    db_path = tmp_path / "api_demo.db"
    initialize_database(db_path)
    settings = Settings(_env_file=None, sqlite_path=db_path)
    app = create_app(settings)
    app.dependency_overrides[get_lab_inject] = lambda: inject
    app.dependency_overrides[get_lab_reset] = lambda: reset
    return TestClient(app), db_path


def test_inject_f1_resolves_catalog_id(tmp_path: Path) -> None:
    seen: list[str] = []
    client, _db = _client(tmp_path, seen.append, lambda: None)
    with client:
        response = client.post("/api/demo/faults/F1/inject")
    assert response.status_code == 200
    assert response.json() == {"fault_id": "backend_stopped"}
    assert seen == ["backend_stopped"]


def test_unknown_fault_does_not_inject(tmp_path: Path) -> None:
    seen: list[str] = []
    client, _db = _client(tmp_path, seen.append, lambda: None)
    with client:
        response = client.post("/api/demo/faults/nope/inject")
    assert response.status_code == 404
    assert seen == []


def test_reset_calls_lab_reset(tmp_path: Path) -> None:
    calls: list[str] = []
    client, _db = _client(tmp_path, lambda _fault: None, lambda: calls.append("reset"))
    with client:
        response = client.post("/api/demo/reset")
    assert response.status_code == 200
    assert response.json() == {"status": "reset"}
    assert calls == ["reset"]


def test_missing_run_is_404(tmp_path: Path) -> None:
    client, _db = _client(tmp_path, lambda _fault: None, lambda: None)
    with client:
        run = client.get("/api/runs/run_missing")
        events = client.get("/api/runs/run_missing/events")
    assert run.status_code == 404
    assert events.status_code == 404


def test_get_run_and_events_in_timestamp_order(tmp_path: Path) -> None:
    client, db_path = _client(tmp_path, lambda _fault: None, lambda: None)
    started = datetime(2026, 1, 1, tzinfo=UTC)
    later = started + timedelta(seconds=1)
    with connection(db_path) as conn:
        insert_agent_run(
            conn,
            AgentRunRecord(
                id="run_c310",
                status="completed",
                final_content="recovered",
                steps=2,
                tool_errors=0,
                tokens=5,
                latency_ms=3,
                policy_violations=0,
            ),
        )
        insert_trace_event(
            conn,
            TraceEvent(
                id="evt_later",
                run_id="run_c310",
                type=TraceEventType.TOOL_RESULT,
                timestamp=later,
                name="docker.restart",
                output={"running": True},
                stage="runtime",
            ),
        )
        insert_trace_event(
            conn,
            TraceEvent(
                id="evt_early",
                run_id="run_c310",
                type=TraceEventType.TOOL_CALL,
                timestamp=started,
                name="docker.restart",
                input={"service": "backend"},
                stage="runtime",
            ),
        )
    with client:
        run = client.get("/api/runs/run_c310")
        events = client.get("/api/runs/run_c310/events")
    assert run.status_code == 200
    assert run.json()["id"] == "run_c310"
    assert run.json()["status"] == "completed"
    assert run.json()["steps"] == 2
    assert run.json()["tokens"] == 5
    assert run.json()["policy_violations"] == 0
    assert events.status_code == 200
    body = events.json()
    assert [item["id"] for item in body] == ["evt_early", "evt_later"]
    assert body[0]["input"] == {"service": "backend"}
    assert body[1]["output"] == {"running": True}
