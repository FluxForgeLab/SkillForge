"""Debug CLI. `run` injects a lab fault; `eval --replay` reads the eval cache."""

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
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.agent_runs import AgentRunRecord, insert_agent_run
from skillforge.db.repositories.projects import get_project
from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.evaluator.cache import replay_trials
from skillforge.evaluator.cases import load_eval_cases
from skillforge.evaluator.errors import CacheMiss
from skillforge.knowledge.retrieval.factory import build_index
from skillforge.knowledge.retrieval.indexer import Indexer
from skillforge.models.adapters.recording import RecordingAdapter
from skillforge.models.gateway import ModelGateway, build_adapter
from skillforge.runtime.agent import AgentRuntime, LocalHarness, RunResult
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import FanOutSink, SqliteTraceSink, TraceSink

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
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if parsed.command == "eval":
        return _eval_replay(parsed)
    if parsed.command == "index":
        return _index_rebuild(parsed)
    return _run(parsed, inject=inject, harness=harness, sink=sink)


def _index_rebuild(parsed: argparse.Namespace) -> int:
    settings = get_settings()
    with connection(settings.sqlite_path) as conn:
        if get_project(conn, parsed.project) is None:
            print(f"unknown project {parsed.project!r}", file=sys.stderr)
            return 2
    asyncio.run(Indexer(settings.sqlite_path, build_index(settings)).rebuild(parsed.project))
    print(f"rebuilt\t{parsed.project}")
    return 0


def _eval_replay(parsed: argparse.Namespace) -> int:
    try:
        cases = load_eval_cases(parsed.skill)
        runs = replay_trials(
            get_settings().sqlite_path,
            version_hash=parsed.version_hash,
            model=parsed.model,
            case_ids=[loaded.case.id for loaded in cases],
        )
    except CacheMiss as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for run in runs:
        case_id = run.metrics["case_id"]
        arm = "control" if run.baseline.get("baseline") is True else "treatment"
        passed = "true" if run.metrics.get("passed") is True else "false"
        print(f"replay\t{case_id}\t{arm}\tpassed={passed}")
    return 0


def _run(
    parsed: argparse.Namespace,
    *,
    inject: Inject | None,
    harness: AgentRuntime | None,
    sink: TraceSink | None,
) -> int:
    try:
        fault_id = resolve_fault(parsed.fault)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    persist = harness is None and sink is None
    memory = ListSink()
    if persist:
        trace_sink: TraceSink = FanOutSink(memory, SqliteTraceSink())
        printable: TraceSink = memory
    elif sink is None:
        trace_sink = memory
        printable = memory
    else:
        trace_sink = sink
        printable = sink
    apply_fault = inject if inject is not None else inject_fault
    try:
        apply_fault(fault_id)
        with tempfile.TemporaryDirectory(prefix="skillforge-run-") as workspace:
            runner = harness if harness is not None else _default_harness(trace_sink)
            result = asyncio.run(runner.run(parsed.task, parsed.skill, workspace))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_trace(printable, result)
    if persist:
        _store_run(result)
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


def reset_fault() -> None:
    script = _repo_root() / "demo" / "ops-lab" / "faults" / "reset.py"
    subprocess.run([sys.executable, str(script)], check=True)


def _store_run(result: RunResult) -> None:
    db_path = get_settings().sqlite_path
    initialize_database(db_path)
    record = AgentRunRecord(
        id=result.run_id,
        status=result.status,
        final_content=result.final_content,
        steps=result.steps,
        tool_errors=result.tool_errors,
        tokens=result.tokens,
        latency_ms=result.latency_ms,
        policy_violations=result.policy_violations,
    )
    with connection(db_path) as conn:
        insert_agent_run(conn, record)


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = _Parser(prog="skillforge")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--task", required=True)
    run.add_argument("--fault", required=True)
    run.add_argument("--skill", default=None)
    eval_cmd = sub.add_parser("eval")
    eval_cmd.add_argument("--skill", required=True)
    eval_cmd.add_argument("--version-hash", required=True)
    eval_cmd.add_argument("--model", required=True)
    eval_cmd.add_argument("--replay", action="store_true", required=True)
    index_cmd = sub.add_parser("index")
    index_sub = index_cmd.add_subparsers(dest="index_command", required=True)
    rebuild = index_sub.add_parser("rebuild")
    rebuild.add_argument("--project", required=True)
    return parser.parse_args(argv)


def _default_harness(sink: TraceSink) -> LocalHarness:
    settings = get_settings()
    adapter = build_adapter(settings)
    transcript = settings.transcript_path.strip()
    if transcript:
        adapter = RecordingAdapter(adapter, Path(transcript))
    gateway = ModelGateway(adapter, settings=settings, sink=sink, bus=EventBus())
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
