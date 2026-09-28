"""C7.8: DoD steps 8–12 — v0.1 fails F3 → patch → v0.2 passes EvolutionGate.

Recorded model drafts + FakeModelAdapter only. No live model, Docker, or ops-lab.
Suite results are synthetic; run_suite is never called.
"""

from __future__ import annotations

import difflib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from skillforge.config import Settings
from skillforge.db import initialize_database
from skillforge.db.connection import connection
from skillforge.db.repositories.projects import insert_project
from skillforge.domain.entities import EvaluationRun, Project, TraceEvent
from skillforge.domain.enums import EvaluationRunStatus, FailureClass, TraceEventType
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.evaluator.assertions import AssertionResult
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
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.registry.service import SkillRegistry
from skillforge.tracing.bus import EventBus

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "evolution" / "f3_self_evolution.json"
_RUNBOOK_INDEX = _ROOT / "fixtures" / "retrieval" / "runbook_index.json"
_GOLDEN = Path(__file__).resolve().parents[3] / "skills" / "golden" / "service-recovery"
_APPENDIX_REF = "doc_runbook#page=31"


def _load_fixture() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        retrieval_backend="memory",
        retrieval_default_mode="keyword",
    )


def _gateway(responses: list[dict]) -> ModelGateway:
    return ModelGateway(
        FakeModelAdapter(
            [ModelResponse(content=json.dumps(payload)) for payload in responses],
        ),
        settings=_settings(),
        bus=EventBus(),
    )


async def _memory_retriever() -> Retriever:
    rows = json.loads(_RUNBOOK_INDEX.read_text(encoding="utf-8"))
    index = MemoryIndex()
    await index.upsert([IndexDocument.model_validate(row) for row in rows])
    return Retriever(
        index=index,
        embedder=NullEmbedder(),
        settings=_settings(),
        bus=EventBus(),
    )


def _events(fixture: dict) -> list[TraceEvent]:
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


def _seed_v01(tmp_path: Path, golden_copy: Path) -> tuple[SkillRegistry, str, Path]:
    db_path = tmp_path / "evolution.db"
    initialize_database(db_path)
    project_id = f"proj_{uuid4().hex}"
    with connection(db_path) as conn:
        insert_project(
            conn,
            Project(
                id=project_id,
                name="Self Evolution F3",
                description=None,
                created_at=datetime.now(UTC),
            ),
        )
    settings = _settings()
    registry = SkillRegistry(
        db_path,
        generated_root=tmp_path / "generated",
        path_prefix=settings.skills_generated_dir.as_posix(),
        settings=settings,
    )
    skill = registry.create_skill(project_id, "service-recovery")
    version = registry.create_version(skill.id, "0.1", _collect_skill_files(golden_copy))
    parent_dir = registry.artifact_dir(version.id)
    return registry, version.id, parent_dir


def _patched_skill_md(original: str, fixture: dict) -> str:
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
        raise AssertionError(f"could not find insert point starting with {prefix!r}")
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


def _synthetic_suites(fixture: dict, *, prev_version: str, cand_version: str):
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


async def test_v01_fails_f3_patch_v02_passes_gate(tmp_path: Path) -> None:
    fixture = _load_fixture()
    run_id = fixture["run_id"]

    golden_copy = tmp_path / "golden_v01"
    shutil.copytree(_GOLDEN, golden_copy)
    parent_skill_md = (golden_copy / "SKILL.md").read_text(encoding="utf-8")
    parent_evals = (golden_copy / "evals" / "evals.json").read_bytes()
    assert "nginx -t" not in parent_skill_md

    registry, parent_version_id, parent_dir = _seed_v01(tmp_path, golden_copy)
    assert "nginx -t" not in (parent_dir / "SKILL.md").read_text(encoding="utf-8")

    # 1) Analyze F3 failure → missing_instruction + Appendix B source_support
    retriever = await _memory_retriever()
    analyzer = FailureAnalyzer(
        _gateway([fixture["failure_draft"]]),
        settings=_settings(),
        retriever=retriever,
        project_id=fixture["project_id"],
    )
    failure = await analyzer.analyze(
        run_id=run_id,
        events=_events(fixture),
        assertion=AssertionResult.model_validate(fixture["assertion"]),
        verifier=fixture["verifier"],
    )
    assert failure.failure_class == FailureClass.MISSING_INSTRUCTION
    assert failure.source_support
    assert _APPENDIX_REF in failure.source_support
    assert "nginx -t" in (failure.suspected_skill_gap or "")

    # 2) Patcher proposes unified diff that adds nginx -t instruction
    new_md = _patched_skill_md(parent_skill_md, fixture)
    assert "nginx -t" in new_md
    diff = _unified(parent_skill_md, new_md)
    assert diff
    patch_draft = {
        "diff": diff,
        "summary": fixture["patch_meta"]["summary"],
        "evidence_refs": fixture["patch_meta"]["evidence_refs"],
    }
    patcher = SkillPatcher(_gateway([patch_draft]), settings=_settings())
    proposal = await patcher.propose(
        skill_dir=parent_dir,
        failure=failure,
        target_skill_version_id=parent_version_id,
        run_id=run_id,
    )
    assert "nginx -t" in proposal.diff
    assert "evals/" not in proposal.diff

    # 3) apply_patch → child DRAFT with source-map for new instruction
    created = apply_patch(
        registry,
        parent_version_id=parent_version_id,
        parent_dir=parent_dir,
        proposal=proposal,
        source_map_updates=fixture["source_map_updates"],
        version="0.2",
    )
    assert created.parent_version_id == parent_version_id
    assert created.status == SkillVersionStatus.DRAFT
    assert created.version == "0.2"

    child_dir = registry.artifact_dir(created.id)
    child_md = (child_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "nginx -t" in child_md
    assert fixture["patch_meta"]["new_instruction_id"] in child_md
    child_evals = (child_dir / "evals" / "evals.json").read_bytes()
    assert child_evals == parent_evals

    source_map = json.loads(
        (child_dir / "references" / "source-map.json").read_text(encoding="utf-8")
    )
    ins_id = fixture["patch_meta"]["new_instruction_id"]
    assert source_map[ins_id]["knowledge_unit_id"] == "ku_appendix_b"
    assert source_map[ins_id]["line_start"] == 31

    # Parent unchanged on disk under registry
    assert "nginx -t" not in (parent_dir / "SKILL.md").read_text(encoding="utf-8")

    # 4) Synthetic previous (F3 fail) vs new (F3 fixed, F1/F2 hold) → gate passes
    previous, candidate = _synthetic_suites(
        fixture,
        prev_version=parent_version_id,
        cand_version=created.id,
    )
    gate = evaluate_evolution_gate(previous=previous, candidate=candidate, failure=failure)
    assert gate.passed is True
    assert gate.failed_conditions == []
    assert all(gate.checks.values())
