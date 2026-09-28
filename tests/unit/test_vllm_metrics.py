"""vLLM /metrics parsing for GET /api/model/status."""

from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from skillforge.api.main import create_app
from skillforge.config import Settings
from skillforge.models.vllm_metrics import (
    metrics_url,
    parse_tokens_per_second,
    read_vllm_tokens_per_second,
)

_SAMPLE = """
# HELP vllm:request_time_per_output_token_seconds Histogram
vllm:request_time_per_output_token_seconds_count{model_name="qwen"} 4.0
vllm:request_time_per_output_token_seconds_sum{model_name="qwen"} 0.5
vllm:request_time_per_output_token_seconds_count{model_name="other"} 9.0
vllm:request_time_per_output_token_seconds_sum{model_name="other"} 9.0
process_resident_memory_bytes 2172506112
"""


def test_metrics_url_strips_v1() -> None:
    assert metrics_url("http://127.0.0.1:8001/v1") == "http://127.0.0.1:8001/metrics"
    assert metrics_url("http://127.0.0.1:8001/v1/") == "http://127.0.0.1:8001/metrics"


def test_parse_tokens_per_second_uses_matching_model_only() -> None:
    rate = parse_tokens_per_second(_SAMPLE, "qwen")
    assert rate == pytest.approx(8.0)


def test_parse_tokens_per_second_is_none_without_samples() -> None:
    assert parse_tokens_per_second(_SAMPLE, "missing") is None
    assert parse_tokens_per_second("", "qwen") is None


@pytest.mark.asyncio
async def test_read_vllm_tokens_per_second_returns_none_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rate = await read_vllm_tokens_per_second(
        "http://127.0.0.1:8001/v1",
        "qwen",
        client=client,
    )
    assert rate is None
    await client.aclose()


def test_model_status_fills_tokens_per_second_from_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_read(base_url: str, model_name: str, **_kwargs: object) -> float:
        assert base_url == "http://127.0.0.1:8001/v1"
        assert model_name == "nvidia/Qwen3.6-35B-A3B-NVFP4"
        return 117.574

    monkeypatch.setattr(
        "skillforge.api.routers.model.read_vllm_tokens_per_second",
        fake_read,
    )
    settings = Settings(
        _env_file=None,
        model_adapter="openai_compatible",
        model_base_url="http://127.0.0.1:8001/v1",
        model_name="nvidia/Qwen3.6-35B-A3B-NVFP4",
        model_api_key="secret-should-not-leak",
    )
    response = TestClient(create_app(settings)).get("/api/model/status")
    assert response.status_code == 200
    assert response.json() == {
        "model": "nvidia/Qwen3.6-35B-A3B-NVFP4",
        "backend": "openai_compatible",
        "tokens_per_second": 117.574,
        "memory_bytes": None,
    }
    assert "secret-should-not-leak" not in response.text
