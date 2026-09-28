"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from skillforge.config import Settings, get_settings
from skillforge.orchestrator.jobs import JobRunner


def get_settings_dep(request: Request) -> Settings:
    stored = getattr(request.app.state, "settings", None)
    if isinstance(stored, Settings):
        return stored
    return get_settings()


def get_job_runner(request: Request) -> JobRunner:
    stored = getattr(request.app.state, "job_runner", None)
    if isinstance(stored, JobRunner):
        return stored
    raise RuntimeError("JobRunner not configured on app.state")
