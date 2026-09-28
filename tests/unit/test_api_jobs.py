"""C8.2: JobRunner status API — GET /api/jobs/{id}, POST cancel."""

from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.testclient import TestClient

from skillforge.api.main import create_app
from skillforge.config import Settings
from skillforge.orchestrator.jobs import JobRunner


def _client(tmp_path: Path, runner: JobRunner | None = None) -> tuple[TestClient, JobRunner]:
    db_path = tmp_path / "api_jobs.db"
    settings = Settings(_env_file=None, sqlite_path=db_path)
    resolved = runner if runner is not None else JobRunner()
    app = create_app(settings, job_runner=resolved)
    client = TestClient(app)
    client.__enter__()
    assert client.app.state.job_runner is resolved
    return client, resolved


def _close(client: TestClient) -> None:
    client.__exit__(None, None, None)


def test_get_unknown_job_returns_404(tmp_path: Path) -> None:
    client, _runner = _client(tmp_path)
    try:
        response = client.get("/api/jobs/job_missing")
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "job not found"
    finally:
        _close(client)


def test_completed_job_returns_result_summary(tmp_path: Path) -> None:
    client, runner = _client(tmp_path)
    try:
        started = asyncio.Event()
        finished = asyncio.Event()

        async def work() -> dict[str, str]:
            started.set()
            await finished.wait()
            return {"ok": "yes"}

        job_id = client.portal.call(runner.submit, work)
        assert job_id.startswith("job_")

        # Wait until running, then let it finish.
        for _ in range(50):
            status = client.get(f"/api/jobs/{job_id}").json()["status"]
            if status == "running":
                break
            client.portal.call(asyncio.sleep, 0.01)
        else:
            raise AssertionError("job never reached running")

        client.portal.call(finished.set)
        for _ in range(50):
            body = client.get(f"/api/jobs/{job_id}").json()
            if body["status"] == "completed":
                break
            client.portal.call(asyncio.sleep, 0.01)
        else:
            raise AssertionError(f"job never completed: {body}")

        assert body == {
            "id": job_id,
            "status": "completed",
            "error": None,
            "result": {"ok": "yes"},
        }
        # Same runner instance as app.state (not a new runner per request).
        assert client.app.state.job_runner.get(job_id) is runner.get(job_id)
    finally:
        _close(client)


def test_failed_job_returns_error_summary(tmp_path: Path) -> None:
    client, runner = _client(tmp_path)
    try:

        async def boom() -> None:
            raise RuntimeError("boom")

        job_id = client.portal.call(runner.submit, boom)
        for _ in range(50):
            body = client.get(f"/api/jobs/{job_id}").json()
            if body["status"] == "failed":
                break
            client.portal.call(asyncio.sleep, 0.01)
        else:
            raise AssertionError(f"job never failed: {body}")

        assert body["id"] == job_id
        assert body["status"] == "failed"
        assert body["error"] == "boom"
        assert body["result"] is None
    finally:
        _close(client)


def test_cancel_running_job(tmp_path: Path) -> None:
    client, runner = _client(tmp_path)
    try:
        gate = asyncio.Event()

        async def slow() -> str:
            await gate.wait()
            return "never"

        job_id = client.portal.call(runner.submit, slow)
        for _ in range(50):
            if client.get(f"/api/jobs/{job_id}").json()["status"] == "running":
                break
            client.portal.call(asyncio.sleep, 0.01)
        else:
            raise AssertionError("job never reached running")

        cancel = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel.status_code == 200
        assert cancel.json()["status"] == "cancelled"

        again = client.get(f"/api/jobs/{job_id}")
        assert again.status_code == 200
        assert again.json()["status"] == "cancelled"
    finally:
        _close(client)


def test_cancel_finished_job_returns_409(tmp_path: Path) -> None:
    client, runner = _client(tmp_path)
    try:

        async def quick() -> str:
            return "done"

        job_id = client.portal.call(runner.submit, quick)
        for _ in range(50):
            if client.get(f"/api/jobs/{job_id}").json()["status"] == "completed":
                break
            client.portal.call(asyncio.sleep, 0.01)
        else:
            raise AssertionError("job never completed")

        response = client.post(f"/api/jobs/{job_id}/cancel")
        assert response.status_code == 409
        assert "cannot be cancelled" in response.json()["error"]["message"]
    finally:
        _close(client)


def test_cancel_unknown_job_returns_404(tmp_path: Path) -> None:
    client, _runner = _client(tmp_path)
    try:
        response = client.post("/api/jobs/job_missing/cancel")
        assert response.status_code == 404
    finally:
        _close(client)


def test_create_app_reuses_injected_runner(tmp_path: Path) -> None:
    runner = JobRunner()
    client, resolved = _client(tmp_path, runner=runner)
    try:
        assert resolved is runner
        assert client.app.state.job_runner is runner
        # get_job_runner dependency must resolve the same instance.
        r1 = client.get("/api/jobs/does-not-exist")
        r2 = client.get("/api/jobs/does-not-exist")
        assert r1.status_code == 404
        assert r2.status_code == 404
        assert client.app.state.job_runner is runner
    finally:
        _close(client)
