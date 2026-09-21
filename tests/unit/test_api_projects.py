"""C2.8: Projects API endpoints."""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from skillforge.api.main import create_app
from skillforge.config import Settings
from skillforge.db import initialize_database


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "api_projects.db"
    initialize_database(db_path)
    settings = Settings(_env_file=None, sqlite_path=db_path)
    return TestClient(create_app(settings))


def test_create_project_returns_201(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/projects",
            json={"name": "Service Recovery Demo", "description": "ops-lab"},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Service Recovery Demo"
    assert body["description"] == "ops-lab"
    assert body["id"].startswith("proj_")
    assert body["created_at"]


def test_list_projects_includes_created(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        created = client.post("/api/projects", json={"name": "Alpha"}).json()
        response = client.get("/api/projects")

    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["id"] == created["id"]
    assert projects[0]["name"] == "Alpha"


def test_create_project_validation_error(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/projects", json={"name": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
