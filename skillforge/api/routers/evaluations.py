"""Evaluate a skill as a background job; read stored evaluation runs."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from skillforge.api.deps import get_settings_dep
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.repositories.evaluation_runs import get_evaluation_run
from skillforge.db.repositories.skill_versions import get_skill_version
from skillforge.db.repositories.skills import get_skill
from skillforge.domain.entities import EvaluationRun
from skillforge.domain.enums import TraceEventType
from skillforge.evaluator.cases import load_eval_cases
from skillforge.evaluator.suite import run_suite
from skillforge.models.gateway import ModelGateway, build_adapter
from skillforge.runtime.agent import LocalHarness
from skillforge.tracing.bus import EventBus
from skillforge.tracing.emitter import emit
from skillforge.tracing.sink import SqliteTraceSink, TraceSink

router = APIRouter(prefix="/skills", tags=["evaluations"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]

EvaluateRunner = Callable[..., Awaitable[list[str]]]


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repeats: int = Field(default=1, ge=1)


_DEFAULT_EVALUATE_REQUEST = EvaluateRequest()


class EvaluateJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str


class EvaluationRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    skill_version_id: str
    baseline: dict[str, Any]
    metrics: dict[str, Any]
    status: str
    started_at: datetime
    finished_at: datetime | None


async def default_evaluate_runner(
    *,
    skill_id: str,
    skill_version_id: str,
    skill_dir: str,
    repeats: int,
    settings: Settings,
    bus: EventBus,
) -> list[str]:
    """Run Control vs Treatment via run_suite. Tests must override get_evaluate_runner."""
    _ = skill_id
    cases = load_eval_cases(skill_dir)
    adapter = build_adapter(settings)

    def harness_factory(run_id: str, sink: TraceSink) -> LocalHarness:
        gateway = ModelGateway(adapter, settings=settings, sink=sink, bus=bus)
        return LocalHarness(
            gateway=gateway,
            settings=settings,
            sink=sink,
            bus=bus,
            run_id=run_id,
        )

    with tempfile.TemporaryDirectory(prefix="skillforge-eval-") as workspace:
        report = await run_suite(
            cases,
            skill_path=skill_dir,
            skill_version_id=skill_version_id,
            workspace=workspace,
            harness_factory=harness_factory,
            db_path=settings.sqlite_path,
            repeats=repeats,
        )
    return [run.id for run in report.runs]


def get_evaluate_runner() -> EvaluateRunner:
    return default_evaluate_runner


def _to_response(run: EvaluationRun) -> EvaluationRunResponse:
    return EvaluationRunResponse(
        id=run.id,
        skill_version_id=run.skill_version_id,
        baseline=run.baseline,
        metrics=run.metrics,
        status=run.status.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def _run_evaluate_job(
    *,
    job_id: str,
    skill_id: str,
    skill_version_id: str,
    skill_dir: str,
    repeats: int,
    settings: Settings,
    bus: EventBus,
    runner: EvaluateRunner,
) -> None:
    sink = SqliteTraceSink(settings.sqlite_path)
    await emit(
        job_id,
        TraceEventType.WORKFLOW_STARTED,
        name="evaluate",
        stage="evaluator",
        input={
            "skill_id": skill_id,
            "repeats": repeats,
            "skill_version_id": skill_version_id,
        },
        bus=bus,
        sink=sink,
    )
    try:
        run_ids = await runner(
            skill_id=skill_id,
            skill_version_id=skill_version_id,
            skill_dir=skill_dir,
            repeats=repeats,
            settings=settings,
            bus=bus,
        )
        await emit(
            job_id,
            TraceEventType.EVALUATION_COMPLETED,
            name="evaluate",
            stage="evaluator",
            output={"run_ids": run_ids, "status": "completed"},
            bus=bus,
            sink=sink,
        )
    except Exception as exc:
        await emit(
            job_id,
            TraceEventType.EVALUATION_COMPLETED,
            name="evaluate",
            stage="evaluator",
            output={"status": "failed", "error": str(exc)},
            bus=bus,
            sink=sink,
        )


def _resolve_skill_for_evaluate(
    db_path: Path,
    skill_id: str,
) -> tuple[str, str]:
    """Return (skill_version_id, artifact_path) or raise HTTPException."""
    with connection(db_path) as conn:
        skill = get_skill(conn, skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail="skill not found")
        if not skill.current_version_id:
            raise HTTPException(status_code=409, detail="skill has no current version")
        version = get_skill_version(conn, skill.current_version_id)
        if version is None:
            raise HTTPException(status_code=409, detail="skill current version missing")
        artifact = version.artifact_path
        if artifact is None or not str(artifact).strip():
            raise HTTPException(status_code=409, detail="skill version has no artifact path")
        return version.id, str(artifact)


def _load_evaluation_for_skill(
    db_path: Path,
    skill_id: str,
    run_id: str,
) -> EvaluationRun | None:
    with connection(db_path) as conn:
        run = get_evaluation_run(conn, run_id)
        if run is None:
            return None
        version = get_skill_version(conn, run.skill_version_id)
        if version is None or version.skill_id != skill_id:
            return None
        return run


@router.post(
    "/{skill_id}/evaluate",
    response_model=EvaluateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_evaluate(
    skill_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    settings: SettingsDep,
    runner: Annotated[EvaluateRunner, Depends(get_evaluate_runner)],
    body: EvaluateRequest = _DEFAULT_EVALUATE_REQUEST,
) -> EvaluateJobResponse:
    version_id, skill_dir = await asyncio.to_thread(
        _resolve_skill_for_evaluate,
        settings.sqlite_path,
        skill_id,
    )
    bus: EventBus = request.app.state.bus
    job_id = "job_" + uuid4().hex
    background_tasks.add_task(
        _run_evaluate_job,
        job_id=job_id,
        skill_id=skill_id,
        skill_version_id=version_id,
        skill_dir=skill_dir,
        repeats=body.repeats,
        settings=settings,
        bus=bus,
        runner=runner,
    )
    return EvaluateJobResponse(job_id=job_id)


@router.get(
    "/{skill_id}/evaluations/{run_id}",
    response_model=EvaluationRunResponse,
)
async def get_skill_evaluation(
    skill_id: str,
    run_id: str,
    settings: SettingsDep,
) -> EvaluationRunResponse:
    run = await asyncio.to_thread(
        _load_evaluation_for_skill,
        settings.sqlite_path,
        skill_id,
        run_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="evaluation run not found")
    return _to_response(run)
