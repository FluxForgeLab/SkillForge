from __future__ import annotations

from pathlib import Path

import pytest

from skillforge.config import Settings
from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.errors import ModelScriptExhaustedError
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelRequest, ModelResponse, TokenUsage, ToolCall
from skillforge.runtime.agent import LocalHarness
from skillforge.runtime.prompt import system_prompt
from skillforge.sandbox.base import ExecResult, Sandbox
from skillforge.tracing.bus import EventBus


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


class RecordingFake(FakeModelAdapter):
    def __init__(self, script: list[ModelResponse]) -> None:
        super().__init__(script)
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return await super().generate(request)


class FakeSandbox(Sandbox):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[str] = []
        self.destroyed = False

    async def _create(self) -> None:
        return None

    async def _exec(self, command: str, *, timeout_sec: float) -> ExecResult:
        del timeout_sec
        self.commands.append(command)
        return ExecResult(exit_code=0, stdout="ok\n", stderr="")

    async def _read_file(self, path: str) -> str:
        del path
        return ""

    async def _write_file(self, path: str, content: str) -> None:
        del path, content

    async def _destroy(self) -> None:
        self.destroyed = True


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "max_steps": 5,
        "max_seconds": 30,
        "temperature": 0.2,
        "seed": 7,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _harness(
    script: list[ModelResponse],
    settings: Settings,
    sandbox: FakeSandbox,
    sink: ListSink,
) -> tuple[LocalHarness, RecordingFake]:
    adapter = RecordingFake(script)
    gateway = ModelGateway(adapter, settings=settings, sink=sink, bus=EventBus())
    harness = LocalHarness(
        gateway=gateway,
        settings=settings,
        sandbox=sandbox,
        sink=sink,
        bus=EventBus(),
        run_id="run_c36",
    )
    return harness, adapter


def _tool_response(name: str, arguments: str, *, tokens: int = 3) -> ModelResponse:
    return ModelResponse(
        tool_calls=[ToolCall(id="call_1", name=name, arguments=arguments)],
        finish_reason="tool_calls",
        usage=TokenUsage(total_tokens=tokens),
    )


def _done(content: str = "recovered", *, tokens: int = 2) -> ModelResponse:
    return ModelResponse(
        content=content,
        finish_reason="stop",
        usage=TokenUsage(total_tokens=tokens),
    )


async def test_loop_completes_after_tool_call(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text("secret skill", encoding="utf-8")
    sandbox = FakeSandbox()
    sink = ListSink()
    settings = _settings()
    harness, adapter = _harness(
        [_tool_response("shell.read", '{"command": "ls /workspace"}'), _done()],
        settings,
        sandbox,
        sink,
    )
    result = await harness.run("restore the service", str(skill), str(tmp_path))
    assert result.status == "completed"
    assert result.final_content == "recovered"
    assert result.steps == 2
    assert result.tool_errors == 0
    assert result.policy_violations == 0
    assert result.tokens == 5
    assert result.run_id == "run_c36"
    assert sandbox.commands == ["ls /workspace"]
    assert sandbox.destroyed is True
    assert len(adapter.requests) == 2
    assert adapter.requests[0].temperature == 0.2
    assert adapter.requests[0].seed == 7
    tool_names = {tool.name for tool in adapter.requests[0].tools}
    assert {"http.get", "docker.restart"} <= tool_names
    assert [message.role for message in adapter.requests[1].messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert system_prompt(None) == system_prompt(str(skill))
    assert adapter.requests[0].messages[0].content == system_prompt(None)
    assert "secret skill" not in (adapter.requests[0].messages[0].content or "")


async def test_max_steps_stops_before_next_generate() -> None:
    sandbox = FakeSandbox()
    sink = ListSink()
    harness, adapter = _harness(
        [
            _tool_response("shell.read", '{"command": "ls /workspace"}'),
            _tool_response("shell.read", '{"command": "ls /workspace"}'),
        ],
        _settings(max_steps=1),
        sandbox,
        sink,
    )
    result = await harness.run("restore", None, "/tmp/workspace")
    assert result.status == "exhausted"
    assert result.steps == 1
    assert result.final_content is None
    assert len(adapter.requests) == 1
    assert sandbox.destroyed is True


async def test_zero_second_budget_skips_the_model() -> None:
    sandbox = FakeSandbox()
    sink = ListSink()
    harness, adapter = _harness(
        [_done()],
        _settings(max_seconds=0),
        sandbox,
        sink,
    )
    result = await harness.run("restore", None, "/tmp/workspace")
    assert result.status == "exhausted"
    assert result.steps == 0
    assert adapter.requests == []
    assert sandbox.destroyed is True


async def test_policy_violation_is_counted_and_run_continues() -> None:
    sandbox = FakeSandbox()
    sink = ListSink()
    harness, _adapter = _harness(
        [
            _tool_response("docker.restart", '{"service": "mock-db"}'),
            _done(content="stopped"),
        ],
        _settings(),
        sandbox,
        sink,
    )
    result = await harness.run("restore", None, "/tmp/workspace")
    assert result.status == "completed"
    assert result.policy_violations == 1
    assert result.tool_errors == 0
    assert any(event.type is TraceEventType.POLICY_VIOLATION for event in sink.events)
    assert sandbox.destroyed is True


async def test_exhausted_script_still_destroys_sandbox() -> None:
    sandbox = FakeSandbox()
    sink = ListSink()
    harness, _adapter = _harness([], _settings(), sandbox, sink)
    with pytest.raises(ModelScriptExhaustedError):
        await harness.run("restore", None, "/tmp/workspace")
    assert sandbox.destroyed is True
