"""Headless 15-step DoD path for ``skillforge demo`` (judge-mode replay / live).

Pipeline stays on the PASSED branch — never PipelineState.FAILED — so approve/publish
remain reachable. The printed ``failure`` step is an evaluation outcome (v0.1 misses F3),
not a pipeline terminal state.

``demo_mode=replay`` (default) uses the recorded FakeModel path. ``demo_mode=live``
still uses the recorded analyzer/patcher fixture (precomputed benchmark) but runs
exactly one live agent case — F1 ``backend_stopped`` — during execute. Explicit CLI
``--replay`` forces the recorded path even when settings say live.
"""

from __future__ import annotations

import asyncio
import difflib
import inspect
import json
import shutil
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from skillforge.config import DemoMode, Settings, get_settings
from skillforge.db import initialize_database
from skillforge.db.connection import connection
from skillforge.db.repositories.projects import insert_project
from skillforge.domain.entities import EvaluationRun, Project, TraceEvent
from skillforge.domain.enums import EvaluationRunStatus, TraceEventType
from skillforge.domain.state_machines import PipelineState, SkillVersionStatus
from skillforge.evaluator.assertions import AssertionResult
from skillforge.evaluator.cases import load_eval_cases
from skillforge.evaluator.suite import summarize
from skillforge.evolution.analyzer import FailureAnalyzer
from skillforge.evolution.apply import apply_patch
from skillforge.evolution.gate import evaluate_evolution_gate
from skillforge.evolution.patcher import SkillPatcher
from skillforge.knowledge.retrieval.backends.memory import MemoryIndex
from skillforge.knowledge.retrieval.base import IndexDocument
from skillforge.knowledge.retrieval.embedder import NullEmbedder
from skillforge.knowledge.retrieval.retriever import Retriever
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway, build_adapter
from skillforge.models.types import ModelResponse
from skillforge.orchestrator.pipeline import PipelineRun
from skillforge.registry.human import approve, publish
from skillforge.registry.service import SkillRegistry
from skillforge.runtime.agent import AgentRuntime, LocalHarness
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import TraceSink

Inject = Callable[[str], None]
Reset = Callable[[], None]
Verify = Callable[[], Mapping[str, Any]]
DemoHook = Callable[[], Any]

DEMO_STEPS: tuple[str, ...] = (
    "upload",
    "extract",
    "compile",
    "inject",
    "execute",
    "evaluate",
    "failure",
    "patch",
    "regression",
    "approve",
    "publish",
)

_DEMO_APPROVER = "demo-judge"
_REPLAY_FAULT = "nginx_bad_config_reload"
_LIVE_FAULT = "backend_stopped"
_FIXTURE_REL = Path("tests") / "fixtures" / "demo" / "dod_replay.json"
_RUNBOOK_INDEX_REL = Path("tests") / "fixtures" / "retrieval" / "runbook_index.json"
_GOLDEN_REL = Path("skills") / "golden" / "service-recovery"


def resolve_demo_replay(*, cli_replay: bool, demo_mode: DemoMode) -> bool:
    """``--replay`` wins; otherwise follow ``Settings.demo_mode`` (default replay)."""
    return bool(cli_replay) or demo_mode == "replay"


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


def run_dod_demo(
    *,
    replay: bool,
    repo_root: Path,
    settings: Settings | None = None,
    inject: Inject | None = None,
    reset: Reset | None = None,
    verify: Verify | None = None,
    fixture_path: Path | None = None,
    sink: TraceSink | None = None,
    work_dir: Path | None = None,
    harness: AgentRuntime | None = None,
    gateway: ModelGateway | None = None,
    live_runner: DemoHook | None = None,
    replay_runner: DemoHook | None = None,
) -> int:
    """Run the headless DoD. Returns 0 on green recorded/live path."""
    return _run_async(
        replay=replay,
        repo_root=repo_root,
        settings=settings,
        inject=inject,
        reset=reset,
        verify=verify,
        fixture_path=fixture_path,
        sink=sink,
        work_dir=work_dir,
        harness=harness,
        gateway=gateway,
        live_runner=live_runner,
        replay_runner=replay_runner,
    )


def _run_async(**kwargs: Any) -> int:
    return asyncio.run(_run_dod(**kwargs))


async def _run_dod(
    *,
    replay: bool,
    repo_root: Path,
    settings: Settings | None,
    inject: Inject | None,
    reset: Reset | None,
    verify: Verify | None,
    fixture_path: Path | None,
    sink: TraceSink | None,
    work_dir: Path | None,
    harness: AgentRuntime | None,
    gateway: ModelGateway | None,
    live_runner: DemoHook | None,
    replay_runner: DemoHook | None,
) -> int:
    resolved = settings if settings is not None else get_settings()
    fixture = _load_fixture(fixture_path if fixture_path is not None else repo_root / _FIXTURE_REL)
    if replay:
        apply_inject = inject if inject is not None else _noop_inject
        apply_reset = reset if reset is not None else _noop_reset
        apply_verify = verify if verify is not None else _noop_verify
    else:
        apply_inject = inject if inject is not None else _default_inject(repo_root)
        apply_reset = reset if reset is not None else _default_reset(repo_root)
        apply_verify = verify if verify is not None else _default_verify(repo_root)
    trace_sink: TraceSink = sink if sink is not None else ListSink()
    bus = EventBus()

    own_work = work_dir is None
    root = work_dir if work_dir is not None else Path(tempfile.mkdtemp(prefix="skillforge-demo-"))
    try:
        db_path = root / "skillforge.db"
        initialize_database(db_path)
        demo_settings = resolved.model_copy(
            update={
                "sqlite_path": db_path,
                "skills_generated_dir": root / "generated",
                "skills_published_dir": root / "published",
                "retrieval_backend": "memory",
                "retrieval_default_mode": "keyword",
            }
        )

        project_id = fixture["project_id"]
        with connection(db_path) as conn:
            insert_project(
                conn,
                Project(
                    id=project_id,
                    name="DoD Demo",
                    description=None,
                    created_at=datetime.now(UTC),
                ),
            )

        registry = SkillRegistry(
            db_path,
            generated_root=demo_settings.skills_generated_dir,
            published_root=demo_settings.skills_published_dir,
            path_prefix=demo_settings.skills_generated_dir.as_posix(),
            settings=demo_settings,
        )
        pipeline = PipelineRun(fixture["run_id"], sink=trace_sink, bus=bus)

        # 1 upload — pipeline starts INGESTED
        _step("upload")

        # 2 extract
        await pipeline.advance(PipelineState.EXTRACTED)
        _step("extract")

        # 3 compile — package golden v0.1 (no nginx -t); advance to CANDIDATE
        golden_src = repo_root / _GOLDEN_REL
        golden_copy = root / "golden_v01"
        shutil.copytree(golden_src, golden_copy)
        parent_md = (golden_copy / "SKILL.md").read_text(encoding="utf-8")
        if "nginx -t" in parent_md:
            raise RuntimeError("v0.1 golden must not contain nginx -t before patch")
        parent_evals = (golden_copy / "evals" / "evals.json").read_bytes()
        skill = registry.create_skill(project_id, "service-recovery")
        parent = registry.create_version(skill.id, "0.1", _collect_skill_files(golden_copy))
        registry.transition(parent.id, SkillVersionStatus.CANDIDATE)
        parent_dir = registry.artifact_dir(parent.id)
        await pipeline.advance(PipelineState.DRAFTED)
        await pipeline.advance(PipelineState.VALIDATING)
        await pipeline.advance(PipelineState.CANDIDATE)
        _step("compile")

        # 4 inject — F3 story fault in replay; F1 only in live (not the 3-case matrix)
        fault_id = _REPLAY_FAULT if replay else _LIVE_FAULT
        apply_inject(fault_id)
        _step("inject")

        # 5 execute — replay: recorded noop/hook; live: exactly one F1 agent case
        await _run_execute(
            replay=replay,
            skill_dir=parent_dir,
            workspace=root / "live_workspace",
            settings=demo_settings,
            harness=harness,
            sink=trace_sink,
            bus=bus,
            live_runner=live_runner,
            replay_runner=replay_runner,
        )
        _step("execute")

        # 6 evaluate — F3 fails on v0.1; pipeline takes PASSED (not FAILED)
        await pipeline.advance(PipelineState.EVALUATING)
        await pipeline.advance(PipelineState.PASSED)
        _step("evaluate")

        # 7 failure — FailureAnalyzer (evaluation miss, not PipelineState.FAILED)
        # Analyzer/Patcher always use the recorded FakeModel fixture (precomputed).
        analysis_gateway = gateway
        if analysis_gateway is None:
            analysis_gateway = await _build_gateway(
                fixture=fixture,
                parent_skill_md=parent_md,
                settings=demo_settings,
                sink=trace_sink,
                bus=bus,
            )
        retriever = await _memory_retriever(repo_root, demo_settings, bus)
        analyzer = FailureAnalyzer(
            analysis_gateway,
            settings=demo_settings,
            retriever=retriever,
            project_id=project_id,
        )
        failure = await analyzer.analyze(
            run_id=fixture["run_id"],
            events=_events(fixture),
            assertion=AssertionResult.model_validate(fixture["assertion"]),
            verifier=fixture["verifier"],
        )
        if not failure.source_support:
            raise RuntimeError("failure analysis produced empty source_support")
        _step("failure")

        # 8 patch
        patcher = SkillPatcher(analysis_gateway, settings=demo_settings)
        proposal = await patcher.propose(
            skill_dir=parent_dir,
            failure=failure,
            target_skill_version_id=parent.id,
            run_id=fixture["run_id"],
        )
        child = apply_patch(
            registry,
            parent_version_id=parent.id,
            parent_dir=parent_dir,
            proposal=proposal,
            source_map_updates=fixture["source_map_updates"],
            version="0.2",
        )
        child_dir = registry.artifact_dir(child.id)
        child_md = (child_dir / "SKILL.md").read_text(encoding="utf-8")
        if "nginx -t" not in child_md:
            raise RuntimeError("patched skill must contain nginx -t")
        if (child_dir / "evals" / "evals.json").read_bytes() != parent_evals:
            raise RuntimeError("evals.json must be unchanged by the patch")
        if "nginx -t" in (parent_dir / "SKILL.md").read_text(encoding="utf-8"):
            raise RuntimeError("parent v0.1 must remain without nginx -t")
        _step("patch")

        # 9 regression — synthetic suites + EvolutionGate; promote to CANDIDATE
        previous, candidate = _synthetic_suites(
            fixture,
            prev_version=parent.id,
            cand_version=child.id,
        )
        gate = evaluate_evolution_gate(
            previous=previous,
            candidate=candidate,
            failure=failure,
        )
        if not gate.passed:
            raise RuntimeError(f"evolution gate failed: {gate.failed_conditions}")
        if child.status == SkillVersionStatus.DRAFT:
            child = registry.transition(child.id, SkillVersionStatus.CANDIDATE)
        _step("regression")

        # 10 approve — human-triggered CLI may call approve
        approve(registry, child.id, _DEMO_APPROVER)
        await pipeline.advance(PipelineState.APPROVED)
        _step("approve")

        # 11 publish
        publish(registry, child.id, published_root=demo_settings.skills_published_dir)
        await pipeline.advance(PipelineState.PUBLISHED)
        _step("publish")

        # Lab cleanup hook (no-op when faked)
        apply_reset()
        apply_verify()
        return 0
    finally:
        if own_work:
            shutil.rmtree(root, ignore_errors=True)


def _step(name: str) -> None:
    print(name)


async def _run_execute(
    *,
    replay: bool,
    skill_dir: Path,
    workspace: Path,
    settings: Settings,
    harness: AgentRuntime | None,
    sink: TraceSink,
    bus: EventBus,
    live_runner: DemoHook | None,
    replay_runner: DemoHook | None,
) -> None:
    if replay:
        await _invoke_hook(replay_runner)
        return
    if live_runner is not None:
        await _invoke_hook(live_runner)
        return
    cases = load_eval_cases(skill_dir)
    if not cases:
        raise RuntimeError("live demo requires at least one eval case")
    loaded = cases[0]
    if loaded.fault_id != _LIVE_FAULT:
        raise RuntimeError(
            f"live demo expects first eval fault {_LIVE_FAULT!r}, got {loaded.fault_id!r}"
        )
    workspace.mkdir(parents=True, exist_ok=True)
    runner = harness if harness is not None else _default_live_harness(settings, sink, bus)
    await runner.run(loaded.case.task, str(skill_dir), str(workspace))


async def _invoke_hook(hook: DemoHook | None) -> None:
    if hook is None:
        return
    result = hook()
    if inspect.isawaitable(result):
        await result


def _default_live_harness(
    settings: Settings,
    sink: TraceSink,
    bus: EventBus,
) -> LocalHarness:
    return LocalHarness(
        gateway=ModelGateway(build_adapter(settings), settings=settings, sink=sink, bus=bus),
        settings=settings,
        sink=sink,
        bus=bus,
    )


async def _build_gateway(
    *,
    fixture: dict[str, Any],
    parent_skill_md: str,
    settings: Settings,
    sink: TraceSink,
    bus: EventBus,
) -> ModelGateway:
    """Recorded FakeModel for FailureAnalyzer / Patcher (precomputed judge path)."""
    new_md = _patched_skill_md(parent_skill_md, fixture)
    diff = _unified(parent_skill_md, new_md)
    patch_draft = {
        "diff": diff,
        "summary": fixture["patch_meta"]["summary"],
        "evidence_refs": fixture["patch_meta"]["evidence_refs"],
    }
    script = [
        ModelResponse(content=json.dumps(fixture["failure_draft"])),
        ModelResponse(content=json.dumps(patch_draft)),
    ]
    return ModelGateway(
        FakeModelAdapter(script),
        settings=settings,
        sink=sink,
        bus=bus,
    )


async def _memory_retriever(
    repo_root: Path,
    settings: Settings,
    bus: EventBus,
) -> Retriever:
    rows = json.loads((repo_root / _RUNBOOK_INDEX_REL).read_text(encoding="utf-8"))
    index = MemoryIndex()
    await index.upsert([IndexDocument.model_validate(row) for row in rows])
    return Retriever(
        index=index,
        embedder=NullEmbedder(),
        settings=settings,
        bus=bus,
    )


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _events(fixture: Mapping[str, Any]) -> list[TraceEvent]:
    run_id = fixture["run_id"]
    now = datetime.now(UTC)
    out: list[TraceEvent] = []
    for raw in fixture["events"]:
        out.append(
            TraceEvent(
                id=raw["id"],
                run_id=run_id,
                type=TraceEventType(raw["type"]),
                timestamp=now,
                stage="runtime",
                name=raw.get("name"),
                input=raw.get("input") or {},
                output=raw.get("output") or {},
            )
        )
    return out


def _collect_skill_files(skill_dir: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(skill_dir).as_posix()
        if rel == "manifest.json":
            continue
        files[rel] = path.read_bytes()
    return files


def _patched_skill_md(original: str, fixture: Mapping[str, Any]) -> str:
    meta = fixture["patch_meta"]
    line = meta["new_instruction_line"]
    prefix = meta["insert_after_prefix"]
    lines = original.splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    for item in lines:
        out.append(item)
        if not inserted and item.startswith(prefix):
            ending = "\n" if item.endswith("\n") else ""
            out.append(line + ending)
            inserted = True
    if not inserted:
        raise RuntimeError(f"could not find insert point starting with {prefix!r}")
    return "".join(out)


def _unified(old: str, new: str, *, path: str = "SKILL.md") -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )


def _treatment(
    run_id: str,
    case_id: str,
    *,
    passed: bool,
    version: str,
) -> EvaluationRun:
    now = datetime.now(UTC)
    return EvaluationRun(
        id=run_id,
        skill_version_id=version,
        baseline={"baseline": False},
        metrics={
            "case_id": case_id,
            "passed": passed,
            "latency_ms": 10,
            "tool_errors": 0,
            "policy_violations": 0,
            "forbidden_hits": 0,
        },
        status=EvaluationRunStatus.COMPLETED,
        started_at=now,
        finished_at=now,
    )


def _control(run_id: str, case_id: str, *, version: str) -> EvaluationRun:
    now = datetime.now(UTC)
    return EvaluationRun(
        id=run_id,
        skill_version_id=version,
        baseline={"baseline": True},
        metrics={
            "case_id": case_id,
            "passed": False,
            "latency_ms": 10,
            "tool_errors": 0,
            "policy_violations": 0,
            "forbidden_hits": 0,
        },
        status=EvaluationRunStatus.COMPLETED,
        started_at=now,
        finished_at=now,
    )


def _synthetic_suites(
    fixture: Mapping[str, Any],
    *,
    prev_version: str,
    cand_version: str,
):
    cases = fixture["case_ids"]
    f1, f2, f3 = cases["f1"], cases["f2"], cases["f3"]
    run_id = fixture["run_id"]
    previous = summarize(
        [
            _treatment("prev_f1", f1, passed=True, version=prev_version),
            _treatment("prev_f2", f2, passed=True, version=prev_version),
            _treatment(run_id, f3, passed=False, version=prev_version),
            _control("prev_c1", f1, version=prev_version),
            _control("prev_c2", f2, version=prev_version),
            _control("prev_c3", f3, version=prev_version),
        ],
        skill_version_id=prev_version,
        repeats=1,
    )
    candidate = summarize(
        [
            _treatment("cand_f1", f1, passed=True, version=cand_version),
            _treatment("cand_f2", f2, passed=True, version=cand_version),
            _treatment("cand_f3", f3, passed=True, version=cand_version),
            _control("cand_c1", f1, version=cand_version),
            _control("cand_c2", f2, version=cand_version),
            _control("cand_c3", f3, version=cand_version),
        ],
        skill_version_id=cand_version,
        repeats=1,
    )
    return previous, candidate


def _noop_inject(fault_id: str) -> None:
    del fault_id


def _noop_reset() -> None:
    return None


def _noop_verify() -> Mapping[str, Any]:
    return {"ok": True, "replay": True}


def _default_inject(repo_root: Path) -> Inject:
    def inject(fault_id: str) -> None:
        script = repo_root / "demo" / "ops-lab" / "faults" / "inject.py"
        import subprocess
        import sys

        subprocess.run([sys.executable, str(script), fault_id], check=True)

    return inject


def _default_reset(repo_root: Path) -> Reset:
    def reset() -> None:
        script = repo_root / "demo" / "ops-lab" / "faults" / "reset.py"
        import subprocess
        import sys

        subprocess.run([sys.executable, str(script)], check=True)

    return reset


def _default_verify(repo_root: Path) -> Verify:
    def verify() -> Mapping[str, Any]:
        script = repo_root / "demo" / "ops-lab" / "verifier" / "verify.py"
        import subprocess
        import sys

        completed = subprocess.run(
            [sys.executable, str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.stdout.strip():
            return json.loads(completed.stdout)
        return {"ok": completed.returncode == 0}

    return verify
