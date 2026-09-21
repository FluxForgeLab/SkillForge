from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

_APP_PATH = Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "mock-db" / "app.py"


def _load_mock_db():
    spec = importlib.util.spec_from_file_location("ops_lab_mock_db", _APP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mock_db_health_ok() -> None:
    client = TestClient(_load_mock_db().create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
