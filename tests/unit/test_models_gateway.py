"""C2.5: ModelGateway, Fake and OpenAI-compatible adapters."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from skillforge.config import Settings
from skillforge.domain.enums import TraceEventType
from skillforge.models import (
    ChatMessage,
    FakeModelAdapter,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    ModelScriptExhaustedError,
    OpenAICompatibleAdapter,
    TokenUsage,
    ToolCall,
    ToolDefinition,
    build_adapter,
    fake_adapter_from_script,
    load_fake_script,
)
from skillforge.tracing import EventBus, SqliteTraceSink


def _sample_request(*, run_id: str = "run_test") -> ModelRequest:
    return ModelRequest(
        run_id=run_id,
        stage="runtime",
        messages=[ChatMessage(role="user", content="hello")],
        tools=[ToolDefinition(name="docker.inspect", description="Inspect container")],
    )


@pytest.mark.asyncio
async def test_fake_returns_scripted_responses_in_order() -> None:
    adapter = FakeModelAdapter(
        [
            ModelResponse(content="step-one", finish_reason="stop"),
            ModelResponse(content="step-two", finish_reason="stop"),
        ],
    )
    gateway = ModelGateway(adapter, bus=EventBus())
    request = _sample_request()

    first = await gateway.generate(request)
    second = await gateway.generate(request)

    assert first.content == "step-one"
    assert second.content == "step-two"


@pytest.mark.asyncio
async def test_fake_exhausted_raises() -> None:
    adapter = FakeModelAdapter([ModelResponse(content="only", finish_reason="stop")])
    gateway = ModelGateway(adapter, bus=EventBus())

    await gateway.generate(_sample_request())
    with pytest.raises(ModelScriptExhaustedError):
        await adapter.generate(_sample_request())


@pytest.mark.asyncio
async def test_gateway_emits_request_and_response(tmp_path: Path) -> None:
    bus = EventBus()
    sink = SqliteTraceSink(tmp_path / "model_trace.db")
    received: list[TraceEventType] = []

    async def handler(event) -> None:
        received.append(event.type)

    bus.subscribe(handler)
    adapter = FakeModelAdapter([ModelResponse(content="ok", finish_reason="stop")])
    gateway = ModelGateway(adapter, bus=bus, sink=sink)

    response = await gateway.generate(_sample_request(run_id="run_emit"))

    assert response.content == "ok"
    assert received == [
        TraceEventType.MODEL_REQUEST,
        TraceEventType.MODEL_RESPONSE,
    ]


@pytest.mark.asyncio
async def test_openai_compatible_maps_request_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_abc",
                                    "type": "function",
                                    "function": {
                                        "name": "docker.inspect",
                                        "arguments": '{"container":"backend"}',
                                    },
                                },
                            ],
                        },
                    },
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        base_url="http://example.test/v1",
        transport=transport,
    )
    adapter = OpenAICompatibleAdapter(
        base_url="http://example.test/v1",
        api_key="secret-key",
        default_model="step-3.7-flash",
        default_temperature=0.0,
        client=client,
    )
    gateway = ModelGateway(adapter, bus=EventBus())

    response = await gateway.generate(
        ModelRequest(
            run_id="run_openai",
            messages=[
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="Inspect backend."),
            ],
            tools=[ToolDefinition(name="docker.inspect", parameters={"type": "object"})],
            temperature=0.1,
        ),
    )

    assert captured["path"] == "/v1/chat/completions"
    assert captured["auth"] == "Bearer secret-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "step-3.7-flash"
    assert body["temperature"] == 0.1
    assert body["tools"][0]["function"]["name"] == "docker.inspect"

    assert response.model == "test-model"
    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "docker.inspect"
    assert response.usage.total_tokens == 18

    await client.aclose()


def test_build_adapter_fake_and_openai() -> None:
    fake = build_adapter(Settings(_env_file=None, model_adapter="fake"))
    assert isinstance(fake, FakeModelAdapter)

    openai = build_adapter(Settings(_env_file=None, model_adapter="openai_compatible"))
    assert isinstance(openai, OpenAICompatibleAdapter)


def test_build_adapter_stepfun_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        build_adapter(Settings(_env_file=None, model_adapter="stepfun_local"))


def test_load_fake_script_and_adapter() -> None:
    fixture = Path(__file__).resolve().parent.parent / "fixtures" / "models" / "fake_script.json"
    script = load_fake_script(fixture)
    assert len(script) == 2
    assert script[0].tool_calls[0].name == "docker.inspect"

    adapter = fake_adapter_from_script(fixture)
    assert isinstance(adapter, FakeModelAdapter)


@pytest.mark.asyncio
async def test_fake_script_fixture_playback() -> None:
    fixture = Path(__file__).resolve().parent.parent / "fixtures" / "models" / "fake_script.json"
    gateway = ModelGateway(fake_adapter_from_script(fixture), bus=EventBus())
    request = _sample_request(run_id="run_script")

    first = await gateway.generate(request)
    second = await gateway.generate(request)

    assert first.tool_calls == [
        ToolCall(
            id="call_1",
            name="docker.inspect",
            arguments='{"container":"backend"}',
        ),
    ]
    assert first.usage == TokenUsage(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )
    assert second.content == "Recovery complete."
