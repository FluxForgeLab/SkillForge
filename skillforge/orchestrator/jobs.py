"""In-process asyncio background job runner with cancel and status query."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobNotFound(KeyError):
    """Raised when a job_id is unknown to this runner."""


class JobNotCancellable(RuntimeError):
    """Raised when cancel is requested for a job that already finished."""

    def __init__(self, job_id: str, status: JobStatus) -> None:
        self.job_id = job_id
        self.status = status
        super().__init__(f"job {job_id} is {status.value} and cannot be cancelled")


@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.PENDING
    error: str | None = None
    result: Any | None = None
    _task: asyncio.Task[None] | None = field(default=None, repr=False, compare=False)


class JobRunner:
    """Create jobs, run async callables on asyncio tasks, query status, cancel."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def begin(self, job_id: str) -> Job:
        """Record a job that FastAPI BackgroundTasks will run, so GET can see it."""
        if job_id in self._jobs:
            raise ValueError(f"job id already exists: {job_id}")
        job = Job(id=job_id, status=JobStatus.RUNNING)
        self._jobs[job_id] = job
        return job

    def finish(self, job_id: str, *, result: Any = None, error: str | None = None) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ):
            return
        if error is None:
            job.status = JobStatus.COMPLETED
            job.result = result
            return
        job.status = JobStatus.FAILED
        job.error = error

    def submit(
        self,
        fn: Callable[[], Awaitable[Any]],
        *,
        job_id: str | None = None,
    ) -> str:
        """Register a job and schedule ``fn`` on the running event loop.

        Requires a running loop (e.g. inside a FastAPI request or TestClient portal).
        """
        jid = job_id if job_id is not None else "job_" + uuid4().hex
        if jid in self._jobs:
            raise ValueError(f"job id already exists: {jid}")
        job = Job(id=jid, status=JobStatus.PENDING)
        self._jobs[jid] = job
        loop = asyncio.get_running_loop()
        job._task = loop.create_task(self._execute(job, fn), name=f"skillforge-job-{jid}")
        return jid

    async def _execute(self, job: Job, fn: Callable[[], Awaitable[Any]]) -> None:
        if job.status is JobStatus.CANCELLED:
            return
        job.status = JobStatus.RUNNING
        try:
            result = await fn()
        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            raise
        except Exception as exc:
            if job.status is not JobStatus.CANCELLED:
                job.status = JobStatus.FAILED
                job.error = str(exc)
            return
        if job.status is not JobStatus.CANCELLED:
            job.status = JobStatus.COMPLETED
            job.result = result

    def cancel(self, job_id: str) -> Job:
        """Cancel a pending/running job. Finished jobs raise JobNotCancellable."""
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        if job.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ):
            raise JobNotCancellable(job_id, job.status)
        job.status = JobStatus.CANCELLED
        task = job._task
        if task is not None and not task.done():
            task.cancel()
        return job
