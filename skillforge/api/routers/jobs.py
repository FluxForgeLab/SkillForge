"""Background job status and cancel endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from skillforge.api.deps import get_job_runner
from skillforge.orchestrator.jobs import Job, JobNotCancellable, JobNotFound, JobRunner

router = APIRouter(prefix="/jobs", tags=["jobs"])

JobRunnerDep = Annotated[JobRunner, Depends(get_job_runner)]


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    error: str | None = None
    result: Any | None = Field(default=None)


def _to_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        status=job.status.value,
        error=job.error,
        result=job.result,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, runner: JobRunnerDep) -> JobResponse:
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_response(job)


@router.post(
    "/{job_id}/cancel",
    response_model=JobResponse,
)
async def cancel_job(job_id: str, runner: JobRunnerDep) -> JobResponse:
    try:
        job = runner.cancel(job_id)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="job not found") from None
    except JobNotCancellable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"job is {exc.status.value} and cannot be cancelled",
        ) from None
    return _to_response(job)
