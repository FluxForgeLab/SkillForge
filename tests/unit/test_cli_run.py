from __future__ import annotations

from datetime import UTC, datetime

from skillforge.cli import main
from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.runtime.agent import RunResult


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


class FakeHarness:
    def __init__(self, sink: ListSink, *, status: str = "completed") -> None:
        self.sink = sink
        self.status = status
        self.seen: tuple[str, str | None, str] | None = None

    async def run(self, task: str, skill_path: str | None, workspace: str) -> RunResult:
        self.seen = (task, skill_path, workspace)
        await self.sink.write(
            TraceEvent(
                id="evt_cli",
                run_id="run_cli",
                type=TraceEventType.TOOL_CALL,
                timestamp=datetime.now(UTC),
                name="shell.read",
                input={"command": "ls /workspace"},
                stage="runtime",
            )
        )
        return RunResult(
            run_id="run_cli",
            status=self.status,  # type: ignore[arg-type]
            final_content="recovered",
            steps=2,
            tool_errors=0,
            tokens=5,
            latency_ms=3,
            policy_violations=0,
        )


def test_run_prints_trace_and_result(capsys) -> None:
    injected: list[str] = []
    sink = ListSink()
    harness = FakeHarness(sink)

    def inject(fault_id: str) -> None:
        injected.append(fault_id)

    code = main(
        [
            "run",
            "--task",
            "restore",
            "--fault",
            "F1",
            "--skill",
            "skills/golden/service-recovery",
        ],
        inject=inject,
        harness=harness,
        sink=sink,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert injected == ["backend_stopped"]
    assert harness.seen is not None
    assert harness.seen[0] == "restore"
    assert harness.seen[1] == "skills/golden/service-recovery"
    assert harness.seen[2]
    assert "trace" in out
    assert "tool_call" in out
    assert "result" in out
    assert "status=completed" in out
    assert "steps=2" in out
    assert "tokens=5" in out
    assert "policy_violations=0" in out


def test_fault_id_is_accepted(capsys) -> None:
    injected: list[str] = []
    sink = ListSink()
    harness = FakeHarness(sink)
    code = main(
        ["run", "--task", "restore", "--fault", "backend_stopped"],
        inject=lambda fault_id: injected.append(fault_id),
        harness=harness,
        sink=sink,
    )
    capsys.readouterr()
    assert code == 0
    assert injected == ["backend_stopped"]
    assert harness.seen is not None
    assert harness.seen[1] is None


def test_usage_and_unknown_fault_do_not_inject(capsys) -> None:
    injected: list[str] = []
    sink = ListSink()
    harness = FakeHarness(sink)

    def inject(fault_id: str) -> None:
        injected.append(fault_id)

    missing = main(["run", "--fault", "F1"], inject=inject, harness=harness, sink=sink)
    unknown = main(
        ["run", "--task", "restore", "--fault", "nope"],
        inject=inject,
        harness=harness,
        sink=sink,
    )
    capsys.readouterr()
    assert missing == 2
    assert unknown == 2
    assert injected == []
    assert harness.seen is None
