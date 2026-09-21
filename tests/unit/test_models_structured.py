"""C2.6: Structured output helper with schema retry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from skillforge.config import Settings
from skillforge.models import (
    ChatMessage,
    FakeModelAdapter,
    ModelGateway,
    ModelResponse,
    StructuredOutputError,
    build_schema_instruction,
    extract_json,
    generate_structured,
    parse_structured_content,
)
from skillforge.tracing import EventBus


class MiniModel(BaseModel):
    name: str
    count: int


class RecordingFakeAdapter(FakeModelAdapter):
    def __init__(self, script: list[ModelResponse]) -> None:
        super().__init__(script)
        self.requests: list[list[ChatMessage]] = []

    async def generate(self, request):  # type: ignore[no-untyped-def]
        self.requests.append([m.model_copy(deep=True) for m in request.messages])
        return await super().generate(request)


def test_extract_json_strips_markdown_fence() -> None:
    raw = extract_json('```json\n{"name": "a", "count": 1}\n```')
    assert raw == '{"name": "a", "count": 1}'


def test_parse_structured_content_validates() -> None:
    parsed = parse_structured_content('{"name": "x", "count": 3}', MiniModel)
    assert parsed.name == "x"
    assert parsed.count == 3


@pytest.mark.asyncio
async def test_generate_structured_success_first_try() -> None:
    gateway = ModelGateway(
        FakeModelAdapter(
            [ModelResponse(content='{"name": "ok", "count": 2}', finish_reason="stop")]
        ),
        bus=EventBus(),
    )
    result = await generate_structured(
        gateway,
        MiniModel,
        run_id="run_ok",
        messages=[ChatMessage(role="user", content="Give me data.")],
        settings=Settings(_env_file=None),
    )
    assert result == MiniModel(name="ok", count=2)


@pytest.mark.asyncio
async def test_generate_structured_retries_on_bad_json() -> None:
    adapter = RecordingFakeAdapter(
        [
            ModelResponse(content="not json", finish_reason="stop"),
            ModelResponse(content='{"name": "retry", "count": 1}', finish_reason="stop"),
        ],
    )
    gateway = ModelGateway(adapter, bus=EventBus())
    result = await generate_structured(
        gateway,
        MiniModel,
        run_id="run_retry_json",
        messages=[ChatMessage(role="user", content="Give me data.")],
        settings=Settings(_env_file=None),
    )
    assert result.name == "retry"
    assert len(adapter.requests) == 2
    assert adapter.requests[1][-2].role == "assistant"
    assert adapter.requests[1][-2].content == "not json"
    assert "invalid JSON" in (adapter.requests[1][-1].content or "")


@pytest.mark.asyncio
async def test_generate_structured_retries_on_schema_mismatch() -> None:
    adapter = RecordingFakeAdapter(
        [
            ModelResponse(content='{"name": "x", "count": "nope"}', finish_reason="stop"),
            ModelResponse(content='{"name": "fixed", "count": 4}', finish_reason="stop"),
        ],
    )
    gateway = ModelGateway(adapter, bus=EventBus())
    result = await generate_structured(
        gateway,
        MiniModel,
        run_id="run_retry_schema",
        messages=[ChatMessage(role="user", content="Give me data.")],
        settings=Settings(_env_file=None),
    )
    assert result == MiniModel(name="fixed", count=4)
    assert len(adapter.requests) == 2
    assert "schema validation failed" in (adapter.requests[1][-1].content or "")


@pytest.mark.asyncio
async def test_exhausted_raises_structured_output_error() -> None:
    gateway = ModelGateway(
        FakeModelAdapter(
            [
                ModelResponse(content="bad", finish_reason="stop"),
                ModelResponse(content="still bad", finish_reason="stop"),
                ModelResponse(content="{", finish_reason="stop"),
            ],
        ),
        bus=EventBus(),
    )
    with pytest.raises(StructuredOutputError) as exc_info:
        await generate_structured(
            gateway,
            MiniModel,
            run_id="run_fail",
            messages=[ChatMessage(role="user", content="Give me data.")],
            max_retries=3,
            settings=Settings(_env_file=None),
        )
    err = exc_info.value
    assert err.attempts == 3
    assert err.last_raw == "{"


def test_schema_instruction_contains_schema_properties() -> None:
    instruction = build_schema_instruction(MiniModel)
    assert "MiniModel" in instruction
    assert '"properties"' in instruction
    assert "count" in instruction
