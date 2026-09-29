"""Passes 1–3: choose knowledge units, draft a SkillSpec, then tighten it."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from skillforge.compiler.spec import validate_skill_spec
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.repositories.knowledge_units import list_knowledge_units_by_project
from skillforge.domain.entities import (
    KnowledgeUnit,
    SkillSpec,
    SkillSpecFilesystem,
    SkillSpecNetwork,
    SkillSpecPermissions,
    SkillSpecShell,
)
from skillforge.domain.enums import KnowledgeUnitType
from skillforge.domain.errors import PolicyViolation
from skillforge.knowledge.retrieval.retriever import Retriever
from skillforge.models.gateway import ModelGateway
from skillforge.models.structured import generate_structured
from skillforge.models.types import ChatMessage
from skillforge.runtime.tools.opslab import runtime_tools
from skillforge.sandbox.policy import SandboxPolicy, load_default_policy

_SYSTEM = (
    "Draft a SkillSpec from the supplied knowledge units only. "
    "Do not add tools, paths, hosts, or triggers that those units do not support."
)
_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TaskScope(BaseModel):
    """Caller-owned capability boundary. Triggers are not chosen by the model."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    triggers: list[str]
    types: list[KnowledgeUnitType] = Field(default_factory=list)


class CompiledSpec(BaseModel):
    """A validated SkillSpec plus the knowledge units the model was allowed to see."""

    model_config = ConfigDict(extra="forbid")

    spec: SkillSpec
    selected_unit_ids: list[str]


class NoMatchingKnowledgeError(Exception):
    """Scope triggers matched no stored knowledge-unit trigger."""

    def __init__(self, triggers: list[str]) -> None:
        self.triggers = list(triggers)
        shown = ", ".join(triggers) if triggers else "(none)"
        super().__init__(f"no knowledge units match triggers: {shown}")


async def compile_skill_spec(
    db_path: Path,
    project_id: str,
    scope: TaskScope,
    gateway: ModelGateway,
    *,
    retriever: Retriever,
    settings: Settings,
) -> CompiledSpec:
    """Select units for one scope, ask for a draft, and drop grants the policy rejects."""
    with connection(db_path) as conn:
        units = list_knowledge_units_by_project(conn, project_id)
    eligible = [unit for unit in units if _eligible(unit, scope)]
    selected = await _rank(eligible, scope, project_id, retriever)
    if not selected:
        raise NoMatchingKnowledgeError(list(scope.triggers))
    draft = await generate_structured(
        gateway,
        SkillSpec,
        run_id=f"compile_{project_id}",
        messages=[
            ChatMessage(role="system", content=_SYSTEM),
            ChatMessage(role="user", content=_prompt(selected)),
        ],
        stage="compiler",
        settings=settings,
    )
    spec = validate_skill_spec(_tighten(draft, scope, selected))
    return CompiledSpec(spec=spec, selected_unit_ids=[unit.id for unit in selected])


def _eligible(unit: KnowledgeUnit, scope: TaskScope) -> bool:
    if scope.types and unit.type not in scope.types:
        return False
    trigger = _text(unit.content.get("trigger"))
    if not trigger:
        return False
    folded = trigger.casefold()
    for raw in scope.triggers:
        phrase = raw.strip().casefold()
        if phrase and (phrase in folded or folded in phrase):
            return True
    return False


async def _rank(
    eligible: list[KnowledgeUnit],
    scope: TaskScope,
    project_id: str,
    retriever: Retriever,
) -> list[KnowledgeUnit]:
    if not eligible:
        return []
    query = " ".join(trigger.strip() for trigger in scope.triggers if trigger.strip())
    hits = await retriever.search(query, project_id, kinds=("knowledge_unit",), k=10)
    by_id = {unit.id: unit for unit in eligible}
    ordered: list[KnowledgeUnit] = []
    seen: set[str] = set()
    for hit in hits:
        unit = by_id.get(hit.id)
        if unit is None or hit.id in seen:
            continue
        ordered.append(unit)
        seen.add(hit.id)
    for unit in eligible:
        if unit.id not in seen:
            ordered.append(unit)
    return ordered


def _tighten(draft: SkillSpec, scope: TaskScope, selected: list[KnowledgeUnit]) -> SkillSpec:
    known = {item.name for item in runtime_tools().specs()}
    tools: list[str] = []
    seen_tools: set[str] = set()
    for tool in draft.tools:
        if tool in known and tool not in seen_tools:
            tools.append(tool)
            seen_tools.add(tool)
    policy = load_default_policy()
    permissions = draft.permissions
    sources: list[str] = []
    seen_docs: set[str] = set()
    for unit in selected:
        if unit.document_id not in seen_docs:
            sources.append(unit.document_id)
            seen_docs.add(unit.document_id)
    return draft.model_copy(
        update={
            "name": _skill_name(scope.name, draft.name),
            "triggers": list(scope.triggers),
            "tools": tools,
            "sources": sources,
            "permissions": SkillSpecPermissions(
                filesystem=SkillSpecFilesystem(
                    read=_kept(permissions.filesystem.read, policy.ensure_read),
                    write=_kept(permissions.filesystem.write, policy.ensure_write),
                ),
                network=SkillSpecNetwork(allow=_allowed_hosts(permissions.network.allow, policy)),
                shell=SkillSpecShell(destructive_commands=False),
            ),
        },
    )


def _skill_name(requested: str, drafted: str) -> str:
    """Keep a NVIDIA-legal name. The compile form wins over a model title."""
    for raw in (requested, drafted):
        slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
        if _SKILL_NAME.fullmatch(slug):
            return slug
    return "skill"


def _allowed_hosts(hosts: list[str], policy: SandboxPolicy) -> list[str]:
    allowed = set(policy.network.allow)
    return [host for host in hosts if host in allowed]


def _kept(paths: list[str], check: Callable[[str], None]) -> list[str]:
    kept: list[str] = []
    for path in paths:
        try:
            check(path)
        except PolicyViolation:
            continue
        kept.append(path)
    return kept


def _prompt(selected: list[KnowledgeUnit]) -> str:
    blocks = [_view(unit) for unit in selected]
    if not blocks:
        return "Knowledge units:\n(none)"
    return "Knowledge units:\n\n" + "\n\n".join(blocks)


def _view(unit: KnowledgeUnit) -> str:
    content = unit.content
    lines = [
        f"title: {_text(content.get('title'))}",
        f"type: {unit.type.value}",
        f"trigger: {_text(content.get('trigger'))}",
        "steps:",
        *_bullets(content.get("steps")),
        "success_criteria:",
        *_bullets(content.get("success_criteria")),
        "safety_constraints:",
        *_bullets(content.get("safety_constraints")),
    ]
    return "\n".join(lines)


def _bullets(value: object) -> list[str]:
    if not isinstance(value, list):
        return ["-"]
    items = [_text(item) for item in value if _text(item)]
    return [f"- {item}" for item in items] or ["-"]


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
