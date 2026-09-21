"""Project API routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from skillforge.api.deps import get_settings_dep
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.repositories.projects import insert_project, list_projects
from skillforge.domain.entities import Project

router = APIRouter(prefix="/projects", tags=["projects"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "name must not be blank"
            raise ValueError(msg)
        return normalized


class ProjectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str | None
    created_at: datetime


def _to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
    )


@router.get("", response_model=list[ProjectResponse])
async def get_projects(settings: SettingsDep) -> list[ProjectResponse]:
    def _list() -> list[Project]:
        with connection(settings.sqlite_path) as conn:
            return list_projects(conn)

    projects = await asyncio.to_thread(_list)
    return [_to_response(project) for project in projects]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProjectRequest,
    settings: SettingsDep,
) -> ProjectResponse:
    project = Project(
        id=f"proj_{uuid4().hex}",
        name=body.name,
        description=body.description.strip() if body.description else None,
        created_at=datetime.now(UTC),
    )

    def _insert() -> Project:
        with connection(settings.sqlite_path) as conn:
            insert_project(conn, project)
        return project

    created = await asyncio.to_thread(_insert)
    return _to_response(created)
