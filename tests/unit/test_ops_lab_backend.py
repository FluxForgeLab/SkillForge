from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_APP_PATH = Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "backend" / "app.py"


def _load_backend():
    spec = importlib.util.spec_from_file_location("ops_lab_backend", _APP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTH_PATH", raising=False)
    client = TestClient(_load_backend().create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_items_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTH_PATH", raising=False)
    client = TestClient(_load_backend().create_app())
    response = client.get("/api/items")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["items"], list)
    assert body["items"]


def test_health_path_env_replaces_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTH_PATH", "/ready")
    client = TestClient(_load_backend().create_app())
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok"}
    assert client.get("/health").status_code == 404


def test_health_path_missing_slash_is_prefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTH_PATH", "ready")
    client = TestClient(_load_backend().create_app())
    assert client.get("/ready").status_code == 200
