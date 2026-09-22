"""Debug CLI. `run` injects a lab fault and prints the harness trace."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import yaml

from skillforge.config import get_settings
from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.models.gateway import ModelGateway, build_adapter
from skillforge.runtime.agent import AgentRuntime, LocalHarness, RunResult
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import TraceSink

Inject = Callable[[str], None]


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def main(
    argv: list[str] | None = None,
    *,
    inject: Inject | None = None,
    harness: AgentRuntime | None = None,
    sink: TraceSink | None = None,
) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        parsed = _parse(args)
        fault_id = resolve_fault(parsed.fault)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    trace_sink = sink if sink is not None else ListSink()
    apply_fault = inject if inject is not None else inject_fault
    try:
        apply_fault(fault_id)
        with tempfile.TemporaryDirectory(prefix="skillforge-run-") as workspace:
            runner = harness if harness is not None else _default_harness(trace_sink)
            result = asyncio.run(runner.run(parsed.task, parsed.skill, workspace))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_trace(trace_sink, result)
    return 0 if result.status == "completed" else 1


def resolve_fault(token: str, catalog_path: Path | None = None) -> str:
    path = catalog_path if catalog_path is not None else _catalog_path()
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    faults = loaded["faults"]
    by_id = {item["id"]: item["id"] for item in faults}
    by_label = {item["label"]: item["id"] for item in faults}
    if token in by_id:
        return by_id[token]
    if token in by_label:
        return by_label[token]
    known = ", ".join([*by_id, *by_label])
    raise ValueError(f"unknown fault {token!r}; known: {known}")


def inject_fault(fault_id: str) -> None:
    script = _repo_root() / "demo" / "ops-lab" / "faults" / "inject.py"
    subprocess.run([sys.executable, str(script), fault_id], check=True)


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = _Parser(prog="skillforge")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--task", required=True)
    run.add_argument("--fault", required=True)
    run.add_argument("--skill", default=None)
    return parser.parse_args(argv)


def _default_harness(sink: TraceSink) -> LocalHarness:
    settings = get_settings()
    gateway = ModelGateway(build_adapter(settings), settings=settings, sink=sink, bus=EventBus())
    return LocalHarness(gateway=gateway, settings=settings, sink=sink, bus=EventBus())


def _print_trace(sink: TraceSink, result: RunResult) -> None:
    events = getattr(sink, "events", [])
    for event in events:
        print(_trace_line(event))
    print(
        "result"
        f"\tstatus={result.status}"
        f"\tsteps={result.steps}"
        f"\ttool_errors={result.tool_errors}"
        f"\ttokens={result.tokens}"
        f"\tlatency_ms={result.latency_ms}"
        f"\tpolicy_violations={result.policy_violations}"
    )
    if result.final_content:
        print("final\t" + result.final_content.replace("\n", " "))


def _trace_line(event: TraceEvent) -> str:
    payload = event.input if event.type == TraceEventType.TOOL_CALL else event.output or event.input
    return f"trace\t{event.type}\t{event.name or ''}\t{json.dumps(payload, ensure_ascii=False)}"


def _repo_root() -> Path:
    cwd = Path.cwd()
    catalog = cwd / "demo" / "ops-lab" / "faults" / "catalog.yaml"
    if catalog.is_file():
        return cwd
    return Path(__file__).resolve().parents[1]


def _catalog_path() -> Path:
    return _repo_root() / "demo" / "ops-lab" / "faults" / "catalog.yaml"


if __name__ == "__main__":
    raise SystemExit(main())
