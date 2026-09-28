"""Evolve, approve, publish, and version-diff API endpoints."""

from __future__ import annotations

import difflib
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from skillforge.api.deps import get_settings_dep
from skillforge.api.routers.skills import get_compile_gateway
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.repositories.skills import get_skill
from skillforge.db.repositories.trace_events import list_trace_events_by_run
from skillforge.domain.entities import Failure, PatchProposal, SkillVersion, TraceEvent
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.evaluator.assertions import AssertionResult
from skillforge.evaluator.cases import load_eval_cases
from skillforge.evaluator.suite import SuiteReport
from skillforge.evolution.analyzer import FailureAnalyzer
from skillforge.evolution.apply import apply_patch
from skillforge.evolution.errors import PatchApplyError
from skillforge.evolution.gate import EvolutionGateReport, evaluate_evolution_gate, run_regression
from skillforge.evolution.patcher import SkillPatcher
from skillforge.models.gateway import ModelGateway, build_adapter
from skillforge.registry.errors import (
    DuplicateSkillVersionError,
    MissingApproverError,
    SkillNotFoundError,
    SkillVersionNotFoundError,
)
from skillforge.registry.human import approve as human_approve
from skillforge.registry.human import publish as human_publish
from skillforge.registry.service import SkillRegistry
from skillforge.runtime.agent import LocalHarness
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import TraceSink

router = APIRouter(tags=["evolution"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
GatewayDep = Annotated[ModelGateway, Depends(get_compile_gateway)]

AnalyzeFn = Callable[..., Awaitable[Failure]]
ProposeFn = Callable[..., Awaitable[PatchProposal]]
SuitePairFn = Callable[..., Awaitable[tuple[SuiteReport, SuiteReport]]]

_TEXT_SUFFIXES = frozenset({".md", ".sh", ".py", ".json", ".txt", ".yaml", ".yml"})


class EvolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    parent_version_id: str | None = None
    run_id: str = Field(min_length=1)
    assertion: AssertionResult
    verifier: dict[str, Any] = Field(default_factory=dict)
    events: list[TraceEvent] | None = None
    source_map_updates: dict[str, dict[str, Any]] = Field(default_factory=dict)


class EvolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version_id: str
    status: str
    parent_version_id: str
    gate: EvolutionGateReport
    failure_class: str
    symptom: str
    evidence: list[str] = Field(default_factory=list)
    source_support: list[str] = Field(default_factory=list)


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approver: str = Field(min_length=1)


class ApproveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    status: str
    approver: str


class PublishResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    status: str
    published_path: str


class DiffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    parent_version_id: str | None
    has_parent: bool
    diff: str


def get_evolve_analyze(gateway: GatewayDep, settings: SettingsDep) -> AnalyzeFn:
    async def _analyze(
        *,
        run_id: str,
        events: Sequence[TraceEvent],
        assertion: AssertionResult,
        verifier: Mapping[str, Any],
        project_id: str | None = None,
    ) -> Failure:
        analyzer = FailureAnalyzer(gateway, settings=settings, project_id=project_id)
        return await analyzer.analyze(
            run_id=run_id,
            events=events,
            assertion=assertion,
            verifier=verifier,
            project_id=project_id,
        )

    return _analyze


def get_evolve_propose(gateway: GatewayDep, settings: SettingsDep) -> ProposeFn:
    async def _propose(
        *,
        skill_dir: Path,
        failure: Failure,
        target_skill_version_id: str | None = None,
        run_id: str | None = None,
    ) -> PatchProposal:
        patcher = SkillPatcher(gateway, settings=settings)
        return await patcher.propose(
            skill_dir=skill_dir,
            failure=failure,
            target_skill_version_id=target_skill_version_id,
            run_id=run_id,
        )

    return _propose


def get_evolve_suite_pair(request: Request, settings: SettingsDep) -> SuitePairFn:
    bus: EventBus = request.app.state.bus

    async def _suite_pair(
        *,
        parent_dir: Path,
        candidate_dir: Path,
        parent_version_id: str,
        candidate_version_id: str,
        failure: Failure,
    ) -> tuple[SuiteReport, SuiteReport]:
        _ = failure
        cases = load_eval_cases(str(parent_dir))
        adapter = build_adapter(settings)

        def harness_factory(run_id: str, sink: TraceSink) -> LocalHarness:
            return LocalHarness(
                gateway=ModelGateway(adapter, settings=settings, sink=sink, bus=bus),
                settings=settings,
                sink=sink,
                bus=bus,
                run_id=run_id,
            )

        with tempfile.TemporaryDirectory(prefix="skillforge-evolve-prev-") as prev_ws:
            previous = await run_regression(
                cases,
                skill_path=str(parent_dir),
                skill_version_id=parent_version_id,
                workspace=prev_ws,
                harness_factory=harness_factory,
                db_path=settings.sqlite_path,
            )
        with tempfile.TemporaryDirectory(prefix="skillforge-evolve-cand-") as cand_ws:
            candidate = await run_regression(
                cases,
                skill_path=str(candidate_dir),
                skill_version_id=candidate_version_id,
                workspace=cand_ws,
                harness_factory=harness_factory,
                db_path=settings.sqlite_path,
            )
        return previous, candidate

    return _suite_pair


AnalyzeDep = Annotated[AnalyzeFn, Depends(get_evolve_analyze)]
ProposeDep = Annotated[ProposeFn, Depends(get_evolve_propose)]
SuitePairDep = Annotated[SuitePairFn, Depends(get_evolve_suite_pair)]


@router.post(
    "/skills/{skill_id}/evolve",
    response_model=EvolveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def evolve_skill(
    skill_id: str,
    body: EvolveRequest,
    settings: SettingsDep,
    analyze: AnalyzeDep,
    propose: ProposeDep,
    suite_pair: SuitePairDep,
) -> EvolveResponse:
    """Analyze failure → patch → apply → gate. Stops at DRAFT or CANDIDATE; never approve."""
    registry = _registry(settings)
    skill = _require_skill(settings, skill_id)
    parent = _resolve_parent(registry, skill, body.parent_version_id)
    parent_dir = registry.artifact_dir(parent.id)
    if not parent_dir.is_dir():
        raise HTTPException(status_code=409, detail="parent version artifact missing")

    events = body.events
    if events is None:
        with connection(settings.sqlite_path) as conn:
            events = list_trace_events_by_run(conn, body.run_id)

    failure = await analyze(
        run_id=body.run_id,
        events=events,
        assertion=body.assertion,
        verifier=body.verifier,
        project_id=skill.project_id,
    )
    proposal = await propose(
        skill_dir=parent_dir,
        failure=failure,
        target_skill_version_id=parent.id,
        run_id=body.run_id,
    )
    try:
        created = apply_patch(
            registry,
            parent_version_id=parent.id,
            parent_dir=parent_dir,
            proposal=proposal,
            source_map_updates=body.source_map_updates,
            version=body.version,
        )
    except (PatchApplyError, DuplicateSkillVersionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    candidate_dir = registry.artifact_dir(created.id)
    previous, candidate = await suite_pair(
        parent_dir=parent_dir,
        candidate_dir=candidate_dir,
        parent_version_id=parent.id,
        candidate_version_id=created.id,
        failure=failure,
    )
    gate = evaluate_evolution_gate(previous=previous, candidate=candidate, failure=failure)

    final = created
    if gate.passed and created.status == SkillVersionStatus.DRAFT:
        final = registry.transition(created.id, SkillVersionStatus.CANDIDATE)

    return EvolveResponse(
        skill_id=skill_id,
        version_id=final.id,
        status=final.status.value,
        parent_version_id=parent.id,
        gate=gate,
        failure_class=str(failure.failure_class),
        symptom=failure.symptom,
        evidence=list(failure.evidence),
        source_support=list(failure.source_support),
    )


@router.post(
    "/skills/{skill_id}/versions/{version_id}/approve",
    response_model=ApproveResponse,
)
async def approve_skill_version(
    skill_id: str,
    version_id: str,
    body: ApproveRequest,
    settings: SettingsDep,
) -> ApproveResponse:
    registry = _registry(settings)
    _require_skill_version(settings, skill_id, version_id)
    try:
        result = human_approve(registry, version_id, body.approver)
    except MissingApproverError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SkillVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApproveResponse(
        version_id=result.version.id,
        status=result.version.status.value,
        approver=result.approver,
    )


@router.post(
    "/skills/{skill_id}/versions/{version_id}/publish",
    response_model=PublishResponse,
)
async def publish_skill_version(
    skill_id: str,
    version_id: str,
    settings: SettingsDep,
) -> PublishResponse:
    registry = _registry(settings)
    _require_skill_version(settings, skill_id, version_id)
    try:
        result = human_publish(registry, version_id)
    except SkillVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PublishResponse(
        version_id=result.version.id,
        status=result.version.status.value,
        published_path=str(result.published_path),
    )


@router.get(
    "/skills/{skill_id}/versions/{version_id}/diff",
    response_model=DiffResponse,
)
async def skill_version_diff(
    skill_id: str,
    version_id: str,
    settings: SettingsDep,
) -> DiffResponse:
    registry = _registry(settings)
    version = _require_skill_version(settings, skill_id, version_id)
    if not version.parent_version_id:
        return DiffResponse(
            version_id=version.id,
            parent_version_id=None,
            has_parent=False,
            diff="",
        )
    try:
        parent = registry.get_version(version.parent_version_id)
    except SkillVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    parent_dir = registry.artifact_dir(parent.id)
    child_dir = registry.artifact_dir(version.id)
    return DiffResponse(
        version_id=version.id,
        parent_version_id=parent.id,
        has_parent=True,
        diff=_unified_tree_diff(parent_dir, child_dir),
    )


def _registry(settings: Settings) -> SkillRegistry:
    return SkillRegistry(
        settings.sqlite_path,
        generated_root=settings.skills_generated_dir,
        published_root=settings.skills_published_dir,
        settings=settings,
    )


def _require_skill(settings: Settings, skill_id: str):
    with connection(settings.sqlite_path) as conn:
        skill = get_skill(conn, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="skill not found")
    return skill


def _require_skill_version(settings: Settings, skill_id: str, version_id: str) -> SkillVersion:
    _require_skill(settings, skill_id)
    registry = _registry(settings)
    try:
        version = registry.get_version(version_id)
    except SkillVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if version.skill_id != skill_id:
        raise HTTPException(status_code=404, detail="skill version not found")
    return version


def _resolve_parent(
    registry: SkillRegistry,
    skill,
    parent_version_id: str | None,
) -> SkillVersion:
    if parent_version_id is not None:
        try:
            parent = registry.get_version(parent_version_id)
        except SkillVersionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if parent.skill_id != skill.id:
            raise HTTPException(status_code=404, detail="skill version not found")
        return parent
    if not skill.current_version_id:
        raise HTTPException(status_code=409, detail="skill has no current version")
    try:
        return registry.get_version(skill.current_version_id)
    except SkillVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _unified_tree_diff(parent_dir: Path, child_dir: Path) -> str:
    """Unified diff of SKILL.md plus text scripts between two artifact dirs."""
    paths = sorted(_diffable_relpaths(parent_dir) | _diffable_relpaths(child_dir))
    chunks: list[str] = []
    for rel in paths:
        old_text = _read_text(parent_dir / rel)
        new_text = _read_text(child_dir / rel)
        if old_text == new_text:
            continue
        chunks.append(
            "".join(
                difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                    lineterm="\n",
                )
            )
        )
    return "".join(chunks)


def _diffable_relpaths(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    out: set[str] = set()
    skill_md = root / "SKILL.md"
    if skill_md.is_file():
        out.add("SKILL.md")
    scripts = root / "scripts"
    if scripts.is_dir():
        for path in scripts.rglob("*"):
            if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES:
                out.add(path.relative_to(root).as_posix())
    return out


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")
