from __future__ import annotations

from pathlib import Path

import pytest

from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.domain.errors import PolicyViolation
from skillforge.runtime.tools import ToolContext, runtime_tools
from skillforge.runtime.tools.opslab import docker_inspect
from skillforge.sandbox.base import ExecResult, Sandbox
from skillforge.sandbox.policy import load_default_policy
from skillforge.tracing.bus import EventBus


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


class FakeSandbox(Sandbox):
    async def _create(self) -> None:
        return None

    async def _exec(self, command: str, *, timeout_sec: float) -> ExecResult:
        del command, timeout_sec
        return ExecResult(exit_code=0, stdout="", stderr="")

    async def _read_file(self, path: str) -> str:
        del path
        return ""

    async def _write_file(self, path: str, content: str) -> None:
        del path, content

    async def _destroy(self) -> None:
        return None


async def _context(tmp_path: Path) -> tuple[ToolContext, ListSink]:
    sandbox = FakeSandbox()
    policy = load_default_policy()
    await sandbox.create(policy=policy, workspace=tmp_path)
    ctx = ToolContext(
        sandbox=sandbox,
        policy=policy,
        opslab_base_url="http://127.0.0.1:8088",
    )
    return ctx, ListSink()


@pytest.mark.integration
async def test_restart_backend_and_reject_mock_db(tmp_path: Path, ops_lab: None) -> None:
    del ops_lab
    ctx, sink = await _context(tmp_path)
    registry = runtime_tools()
    result = await registry.call(
        "docker.restart",
        {"service": "backend"},
        ctx,
        run_id="run_c35",
        sink=sink,
        bus=EventBus(),
    )
    assert result["service"] == "backend"
    assert result["running"] is True
    assert [event.type for event in sink.events] == [
        TraceEventType.TOOL_CALL,
        TraceEventType.TOOL_RESULT,
    ]

    denied_sink = ListSink()
    with pytest.raises(PolicyViolation) as denied:
        await registry.call(
            "docker.restart",
            {"service": "mock-db"},
            ctx,
            run_id="run_c35",
            sink=denied_sink,
            bus=EventBus(),
        )
    assert denied.value.name == "restart_database"
    assert [event.type for event in denied_sink.events] == [
        TraceEventType.TOOL_CALL,
        TraceEventType.POLICY_VIOLATION,
    ]
    assert denied_sink.events[0].name == "docker.restart"
    assert denied_sink.events[1].output["name"] == "restart_database"
    assert docker_inspect("mock-db")["running"] is True
