"""Pass 4: fill instruction text, then assign ids and the source map in code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.repositories.knowledge_units import list_knowledge_units_by_document
from skillforge.db.repositories.source_documents import get_source_document
from skillforge.domain.entities import KnowledgeUnit, SkillSpec
from skillforge.models.gateway import ModelGateway
from skillforge.models.structured import generate_structured
from skillforge.models.types import ChatMessage

_SYSTEM = (
    "Write one short instruction sentence per item. "
    "Cite only a knowledge_unit_id from the list. Do not invent instruction ids."
)


class InstructionDraft(BaseModel):
    """One sentence proposed by the model. The compiler assigns the id."""

    model_config = ConfigDict(extra="forbid")

    knowledge_unit_id: str
    text: str
    kind: Literal["procedure", "prohibition"]


class InstructionBatch(BaseModel):
    """Structured output for pass 4."""

    model_config = ConfigDict(extra="forbid")

    instructions: list[InstructionDraft] = Field(default_factory=list)


class SkillMarkdown(BaseModel):
    """In-memory SKILL.md and source-map. Nothing is written to the registry."""

    model_config = ConfigDict(extra="forbid")

    skill_md: str
    source_map: dict[str, dict[str, Any]]


async def render_skill_markdown(
    db_path: Path,
    spec: SkillSpec,
    selected_unit_ids: list[str],
    gateway: ModelGateway,
    *,
    settings: Settings,
) -> SkillMarkdown:
    """Render frontmatter in code and keep only sentences that cite a selected unit."""
    selected = _load_selected(db_path, spec.sources, selected_unit_ids)
    batch = await generate_structured(
        gateway,
        InstructionBatch,
        run_id="compile_skill_md",
        messages=[
            ChatMessage(role="system", content=_SYSTEM),
            ChatMessage(role="user", content=_prompt(selected)),
        ],
        stage="compiler",
        settings=settings,
    )
    kept = _kept(batch.instructions, selected)
    numbered = _number(kept)
    source_map = _source_map(db_path, numbered, selected)
    return SkillMarkdown(skill_md=_document(spec, numbered), source_map=source_map)


def _load_selected(
    db_path: Path,
    document_ids: list[str],
    selected_unit_ids: list[str],
) -> list[KnowledgeUnit]:
    found: dict[str, KnowledgeUnit] = {}
    with connection(db_path) as conn:
        for document_id in document_ids:
            for unit in list_knowledge_units_by_document(conn, document_id):
                found[unit.id] = unit
    return [found[unit_id] for unit_id in selected_unit_ids if unit_id in found]


def _kept(
    drafts: list[InstructionDraft],
    selected: list[KnowledgeUnit],
) -> list[InstructionDraft]:
    allowed = {unit.id for unit in selected}
    kept: list[InstructionDraft] = []
    for draft in drafts:
        if draft.knowledge_unit_id not in allowed:
            continue
        if not draft.text.strip():
            continue
        kept.append(draft)
    return kept


def _number(drafts: list[InstructionDraft]) -> list[tuple[str, InstructionDraft]]:
    procedure = 1
    prohibition = 20
    numbered: list[tuple[str, InstructionDraft]] = []
    for draft in drafts:
        if draft.kind == "prohibition":
            numbered.append((f"ins_{prohibition:02d}", draft))
            prohibition += 1
        else:
            numbered.append((f"ins_{procedure:02d}", draft))
            procedure += 1
    return numbered


def _source_map(
    db_path: Path,
    numbered: list[tuple[str, InstructionDraft]],
    selected: list[KnowledgeUnit],
) -> dict[str, dict[str, Any]]:
    by_id = {unit.id: unit for unit in selected}
    mapped: dict[str, dict[str, Any]] = {}
    with connection(db_path) as conn:
        for instruction_id, draft in numbered:
            unit = by_id[draft.knowledge_unit_id]
            document = get_source_document(conn, unit.document_id)
            filename = document.filename if document is not None else ""
            digest = document.sha256 if document is not None else ""
            mapped[instruction_id] = _entry(unit, filename, digest)
    return mapped


def _entry(unit: KnowledgeUnit, filename: str, sha256: str) -> dict[str, Any]:
    ref = _first_ref(unit)
    entry: dict[str, Any] = {
        "knowledge_unit_id": unit.id,
        "document": filename,
        "sha256": sha256,
    }
    for key in ("page", "line_start", "line_end"):
        value = ref.get(key)
        if value is not None:
            entry[key] = value
    return entry


def _first_ref(unit: KnowledgeUnit) -> dict[str, Any]:
    refs = unit.content.get("source_refs")
    if isinstance(refs, list) and refs and isinstance(refs[0], dict):
        return refs[0]
    if isinstance(unit.source_location, dict):
        return unit.source_location
    return {}


def _line(item: tuple[str, InstructionDraft]) -> str:
    instruction_id, draft = item
    return f"{instruction_id} {draft.text.strip()}"


def _document(spec: SkillSpec, numbered: list[tuple[str, InstructionDraft]]) -> str:
    procedures = [_line(item) for item in numbered if item[1].kind != "prohibition"]
    prohibitions = [_line(item) for item in numbered if item[1].kind == "prohibition"]
    success = "\n".join(spec.success) if spec.success else ""
    triggers = ", ".join(spec.triggers)
    body = "\n".join(
        [
            f"# {spec.name}",
            "",
            "## When to use",
            "",
            spec.description,
            "",
            f"Triggers: {triggers}",
            "",
            "## Procedure",
            "",
            "\n".join(procedures),
            "",
            "## Never do",
            "",
            "\n".join(prohibitions),
            "",
            "## Verification",
            "",
            success,
            "",
        ],
    )
    return _frontmatter(spec) + "\n" + body


def _frontmatter(spec: SkillSpec) -> str:
    payload = {
        "name": spec.name,
        "description": spec.description,
        "version": "0.1.0",
        "triggers": spec.triggers,
        "tools": spec.tools,
        "permissions": spec.permissions.model_dump(),
    }
    dumped = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---"


def _prompt(selected: list[KnowledgeUnit]) -> str:
    lines = ["Selected knowledge units:"]
    for unit in selected:
        title = str(unit.content.get("title") or "").strip()
        lines.append(f"- {unit.id}: {title}")
    return "\n".join(lines)


def source_map_json(source_map: dict[str, dict[str, Any]]) -> str:
    """Serialize the source map the way it is stored under references/."""
    return json.dumps(source_map, indent=2, ensure_ascii=False) + "\n"
