from __future__ import annotations

from pathlib import Path

import pytest

from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.domain.errors import PolicyViolation
from skillforge.runtime.tools import ToolContext, sandbox_tools
from skillforge.sandbox.base import ExecResult, Sandbox
from skillforge.sandbox.policy import load_default_policy
from skillforge.tracing.bus import EventBus


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


class FakeSandbox(Sandbox):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[str] = []
        self.reads: list[str] = []
        self.writes: list[tuple[str, str]] = []

    async def _create(self) -> None:
        return None

    async def _exec(self, command: str, *, timeout_sec: float) -> ExecResult:
        self.commands.append(command)
        return ExecResult(exit_code=0, stdout="200\n", stderr="")

    async def _read_file(self, path: str) -> str:
        self.reads.append(path)
        return "data"

    async def _write_file(self, path: str, content: str) -> None:
        self.writes.append((path, content))

    async def _destroy(self) -> None:
        return None


async def _ready() -> tuple[ToolContext, FakeSandbox, ListSink]:
    sandbox = FakeSandbox()
    policy = load_default_policy()
    await sandbox.create(policy=policy, workspace=Path("/tmp/workspace"))
    ctx = ToolContext(
        sandbox=sandbox,
        policy=policy,
        opslab_base_url="http://127.0.0.1:8088",
    )
    return ctx, sandbox, ListSink()


def test_tool_definitions_match_registry() -> None:
    registry = sandbox_tools()
    names = [spec.name for spec in registry.specs()]
    assert names == ["shell.read", "file.read", "file.write", "http.get"]
    assert [spec.definition().name for spec in registry.specs()] == names


async def test_file_write_allowed_emits_call_then_result() -> None:
    ctx, sandbox, sink = await _ready()
    result = await sandbox_tools().call(
        "file.write",
        {"path": "/workspace/runtime/note.txt", "content": "hello"},
        ctx,
        run_id="run_tools",
        sink=sink,
        bus=EventBus(),
    )
    assert result == {"path": "/workspace/runtime/note.txt", "bytes": 5}
    assert sandbox.writes == [("/workspace/runtime/note.txt", "hello")]
    assert [event.type for event in sink.events] == [
        TraceEventType.TOOL_CALL,
        TraceEventType.TOOL_RESULT,
    ]


async def test_file_write_outside_runtime_emits_policy_violation() -> None:
    ctx, sandbox, sink = await _ready()
    with pytest.raises(PolicyViolation):
        await sandbox_tools().call(
            "file.write",
            {"path": "/workspace/secret", "content": "nope"},
            ctx,
            run_id="run_tools",
            sink=sink,
            bus=EventBus(),
        )
    assert sandbox.writes == []
    assert [event.type for event in sink.events] == [
        TraceEventType.TOOL_CALL,
        TraceEventType.POLICY_VIOLATION,
    ]
    assert sink.events[1].name == "file.write"
    assert sink.events[1].output["kind"] == "filesystem"


async def test_file_read_outside_workspace_emits_policy_violation() -> None:
    ctx, sandbox, sink = await _ready()
    with pytest.raises(PolicyViolation):
        await sandbox_tools().call(
            "file.read",
            {"path": "/etc/passwd"},
            ctx,
            run_id="run_tools",
            sink=sink,
            bus=EventBus(),
        )
    assert sandbox.reads == []
    assert sink.events[-1].type is TraceEventType.POLICY_VIOLATION


async def test_shell_read_whitelist_and_paths() -> None:
    ctx, sandbox, sink = await _ready()
    await sandbox_tools().call(
        "shell.read",
        {"command": "ls /workspace"},
        ctx,
        run_id="run_tools",
        sink=sink,
        bus=EventBus(),
    )
    assert sandbox.commands == ["ls /workspace"]

    with pytest.raises(PolicyViolation):
        await sandbox_tools().call(
            "shell.read",
            {"command": "cat /etc/passwd"},
            ctx,
            run_id="run_tools",
            sink=sink,
            bus=EventBus(),
        )
    assert sandbox.commands == ["ls /workspace"]


async def test_http_get_rewrites_loopback_and_rejects_other_origins() -> None:
    ctx, sandbox, sink = await _ready()
    result = await sandbox_tools().call(
        "http.get",
        {"url": "http://127.0.0.1:8088/health"},
        ctx,
        run_id="run_tools",
        sink=sink,
        bus=EventBus(),
    )
    assert result["url"] == "http://127.0.0.1:8088/health"
    assert result["status"] == 200
    assert "host.docker.internal:8088" in sandbox.commands[0]
    assert sink.events[0].input["url"] == "http://127.0.0.1:8088/health"

    for url in ("http://example.com/", "http://127.0.0.1:8000/health"):
        with pytest.raises(PolicyViolation):
            await sandbox_tools().call(
                "http.get",
                {"url": url},
                ctx,
                run_id="run_tools",
                sink=sink,
                bus=EventBus(),
            )
    assert len(sandbox.commands) == 1


async def test_unknown_tool_raises_before_trace() -> None:
    ctx, _sandbox, sink = await _ready()
    with pytest.raises(KeyError):
        await sandbox_tools().call(
            "docker.restart",
            {},
            ctx,
            run_id="run_tools",
            sink=sink,
            bus=EventBus(),
        )
    assert sink.events == []
