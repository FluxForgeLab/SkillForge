"""Compile a project skill and read the stored versions."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from skillforge.api.deps import get_settings_dep
from skillforge.compiler.evals import render_evals
from skillforge.compiler.package import package_skill
from skillforge.compiler.passes import TaskScope, compile_skill_spec
from skillforge.compiler.scripts import render_scripts
from skillforge.compiler.skill_md import render_skill_markdown, source_map_json
from skillforge.compiler.validate import validate_skill_dir
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.repositories.knowledge_units import list_knowledge_units_by_project
from skillforge.db.repositories.projects import get_project
from skillforge.db.repositories.skill_versions import get_skill_version, list_skill_versions
from skillforge.db.repositories.skills import get_skill
from skillforge.knowledge.retrieval.factory import build_embedder, build_index
from skillforge.knowledge.retrieval.retriever import Retriever
from skillforge.models.gateway import ModelGateway, build_adapter
from skillforge.registry.service import SkillRegistry
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import SqliteTraceSink

router = APIRouter(tags=["skills"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    triggers: list[str] = Field(min_length=1)


class CompileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version_id: str
    status: str


class SkillResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    name: str
    description: str | None
    current_version_id: str | None
    status: str | None


class VersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    status: str
    artifact_path: str | None


class ValidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    errors: list[str]


def get_compile_gateway(request: Request, settings: SettingsDep) -> ModelGateway:
    return ModelGateway(
        build_adapter(settings),
        settings=settings,
        sink=SqliteTraceSink(settings.sqlite_path),
        bus=request.app.state.bus,
    )


GatewayDep = Annotated[ModelGateway, Depends(get_compile_gateway)]


@router.post(
    "/projects/{project_id}/skills/compile",
    response_model=CompileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def compile_project_skill(
    project_id: str,
    body: CompileRequest,
    request: Request,
    settings: SettingsDep,
    gateway: GatewayDep,
) -> CompileResponse:
    _require_project(settings, project_id)
    bus: EventBus = request.app.state.bus
    sink = SqliteTraceSink(settings.sqlite_path)
    retriever = Retriever(
        index=build_index(settings, db_path=settings.sqlite_path),
        embedder=build_embedder(settings),
        settings=settings,
        sink=sink,
        bus=bus,
    )
    compiled = await compile_skill_spec(
        settings.sqlite_path,
        project_id,
        TaskScope(name=body.name, description=body.description, triggers=body.triggers),
        gateway,
        retriever=retriever,
        settings=settings,
    )
    markdown = await render_skill_markdown(
        settings.sqlite_path,
        compiled.spec,
        compiled.selected_unit_ids,
        gateway,
        settings=settings,
    )
    scripts = await render_scripts(compiled.spec, gateway, settings=settings)
    units = _selected_units(settings, project_id, compiled.selected_unit_ids)
    evals = await render_evals(units, gateway, settings=settings)
    with tempfile.TemporaryDirectory(prefix="skillforge-compile-") as tmp:
        skill_dir = _write_skill(
            Path(tmp), markdown.skill_md, markdown.source_map, scripts.files, evals.evals_json
        )
        version = await package_skill(
            skill_dir,
            project_id,
            SkillRegistry(
                settings.sqlite_path,
                generated_root=settings.skills_generated_dir,
                settings=settings,
            ),
            run_id=f"compile_{project_id}",
            sink=sink,
            bus=bus,
        )
    return CompileResponse(
        skill_id=version.skill_id,
        version_id=version.id,
        status=version.status.value,
    )


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill_detail(skill_id: str, settings: SettingsDep) -> SkillResponse:
    with connection(settings.sqlite_path) as conn:
        skill = get_skill(conn, skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail="skill not found")
        status_value = None
        if skill.current_version_id:
            version = get_skill_version(conn, skill.current_version_id)
            if version is not None:
                status_value = version.status.value
    return SkillResponse(
        id=skill.id,
        project_id=skill.project_id,
        name=skill.name,
        description=skill.description,
        current_version_id=skill.current_version_id,
        status=status_value,
    )


@router.get("/skills/{skill_id}/versions", response_model=list[VersionResponse])
async def list_skill_version_details(skill_id: str, settings: SettingsDep) -> list[VersionResponse]:
    with connection(settings.sqlite_path) as conn:
        if get_skill(conn, skill_id) is None:
            raise HTTPException(status_code=404, detail="skill not found")
        versions = list_skill_versions(conn, skill_id)
    return [
        VersionResponse(
            id=version.id,
            version=version.version,
            status=version.status.value,
            artifact_path=version.artifact_path,
        )
        for version in versions
    ]


@router.post("/skills/{skill_id}/validate", response_model=ValidateResponse)
async def validate_skill(
    skill_id: str, request: Request, settings: SettingsDep
) -> ValidateResponse:
    artifact = _artifact_dir(settings, skill_id)
    result = await validate_skill_dir(
        artifact,
        run_id=f"validate_{skill_id}",
        sink=SqliteTraceSink(settings.sqlite_path),
        bus=request.app.state.bus,
    )
    return ValidateResponse(passed=result.passed, errors=result.errors)


def _require_project(settings: Settings, project_id: str) -> None:
    with connection(settings.sqlite_path) as conn:
        if get_project(conn, project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")


def _selected_units(settings: Settings, project_id: str, selected_ids: list[str]) -> list:
    with connection(settings.sqlite_path) as conn:
        units = list_knowledge_units_by_project(conn, project_id)
    by_id = {unit.id: unit for unit in units}
    return [by_id[unit_id] for unit_id in selected_ids if unit_id in by_id]


def _write_skill(
    root: Path,
    skill_md: str,
    source_map: dict,
    scripts: dict[str, str],
    evals_json: str,
) -> Path:
    (root / "references").mkdir()
    (root / "scripts").mkdir()
    (root / "evals").mkdir()
    (root / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (root / "references" / "source-map.json").write_text(
        source_map_json(source_map), encoding="utf-8"
    )
    for name, source in scripts.items():
        (root / "scripts" / name).write_text(source, encoding="utf-8")
    (root / "evals" / "evals.json").write_text(evals_json, encoding="utf-8")
    return root


def _artifact_dir(settings: Settings, skill_id: str) -> Path:
    with connection(settings.sqlite_path) as conn:
        skill = get_skill(conn, skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail="skill not found")
        if not skill.current_version_id:
            raise HTTPException(status_code=409, detail="skill has no current version")
        version = get_skill_version(conn, skill.current_version_id)
    if version is None or not version.artifact_path:
        raise HTTPException(status_code=409, detail="skill version has no artifact path")
    return Path(version.artifact_path)
