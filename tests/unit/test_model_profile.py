"""Settings switch between DGX vLLM and Kimi."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from skillforge.api.main import create_app
from skillforge.api.routers.demo import get_lab_inject, get_lab_reset
from skillforge.config import Settings
from skillforge.db import initialize_database
from skillforge.models.adapters.openai_compatible import OpenAICompatibleAdapter
from skillforge.models.gateway import build_adapter


def test_local_vllm_profile_forces_temperature_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    async def fake_read(base_url: str, model_name: str, **_kwargs: object) -> None:
        seen["base_url"] = base_url
        seen["model_name"] = model_name
        return None

    monkeypatch.setattr("skillforge.api.routers.model.read_vllm_tokens_per_second", fake_read)
    settings = Settings(
        _env_file=None,
        model_profile="local_vllm",
        temperature=1.0,
        model_name="kimi-k3",
        model_api_key="secret-should-not-leak",
    )
    resolved = settings.resolved_model()
    assert resolved.temperature == 0.0
    assert resolved.adapter == "openai_compatible"
    assert resolved.base_url == "http://127.0.0.1:8001/v1"
    assert resolved.name == "nvidia/Qwen3.6-35B-A3B-NVFP4"
    assert resolved.api_key == ""

    adapter = build_adapter(settings)
    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter._default_temperature == 0.0
    assert adapter._default_model == resolved.name

    response = TestClient(create_app(settings)).get("/api/model/status")
    assert response.status_code == 200
    assert response.json()["model"] == resolved.name
    assert response.json()["backend"] == "openai_compatible"
    assert response.json()["memory_bytes"] is None
    assert "secret-should-not-leak" not in response.text
    assert seen == {"base_url": resolved.base_url, "model_name": resolved.name}


def test_kimi_profile_forces_temperature_one() -> None:
    settings = Settings(
        _env_file=None,
        model_profile="kimi",
        temperature=0.0,
        model_api_key="secret-should-not-leak",
    )
    resolved = settings.resolved_model()
    assert resolved.temperature == 1.0
    assert resolved.base_url == "https://api.moonshot.cn/v1"
    assert resolved.name == "kimi-k3"
    assert resolved.api_key == "secret-should-not-leak"
    adapter = build_adapter(settings)
    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter._default_temperature == 1.0


def test_custom_profile_keeps_explicit_temperature() -> None:
    settings = Settings(_env_file=None, temperature=0.2, model_name="step-3.7-flash")
    resolved = settings.resolved_model()
    assert resolved.temperature == 0.2
    assert resolved.name == "step-3.7-flash"
    assert resolved.adapter == "fake"


def test_demo_inject_still_works_on_local_vllm_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "demo.db"
    initialize_database(db_path)
    seen: list[str] = []
    settings = Settings(
        _env_file=None,
        sqlite_path=db_path,
        model_profile="local_vllm",
        temperature=1.0,
    )
    app = create_app(settings)
    app.dependency_overrides[get_lab_inject] = lambda: seen.append
    app.dependency_overrides[get_lab_reset] = lambda: None
    with TestClient(app) as client:
        response = client.post("/api/demo/faults/F1/inject")
    assert response.status_code == 200
    assert response.json() == {"fault_id": "backend_stopped"}
    assert seen == ["backend_stopped"]
