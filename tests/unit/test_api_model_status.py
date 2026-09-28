"""C9.10: GET /api/model/status from Settings only (no invented metrics, no API key)."""

from __future__ import annotations

from starlette.testclient import TestClient

from skillforge.api.main import create_app
from skillforge.config import Settings


def test_model_status_reads_settings_only() -> None:
    settings = Settings(
        _env_file=None,
        model_name="step-3.7-flash",
        model_adapter="fake",
        model_api_key="secret-should-not-leak",
    )
    client = TestClient(create_app(settings))
    response = client.get("/api/model/status")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "model": "step-3.7-flash",
        "backend": "fake",
        "tokens_per_second": None,
        "memory_bytes": None,
    }
    raw = response.text
    assert "secret-should-not-leak" not in raw
    assert "api_key" not in raw.lower()
    assert "model_api_key" not in raw.lower()
