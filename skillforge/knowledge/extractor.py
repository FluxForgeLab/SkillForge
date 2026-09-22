"""Turn stored chunks into knowledge units through structured model output."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from skillforge.config import get_settings
from skillforge.db.connection import connection
from skillforge.db.repositories.chunks import list_chunks_by_document
from skillforge.db.repositories.knowledge_units import (
    delete_knowledge_units_by_document,
    insert_knowledge_unit,
)
from skillforge.domain.entities import Chunk, KnowledgeUnit
from skillforge.domain.enums import KnowledgeUnitType
from skillforge.knowledge.retrieval.base import RetrievalIndex
from skillforge.knowledge.retrieval.factory import build_index
from skillforge.knowledge.retrieval.indexer import Indexer
from skillforge.models.gateway import ModelGateway
from skillforge.models.structured import generate_structured
from skillforge.models.types import ChatMessage

_SYSTEM = (
    "Extract knowledge units from one document chunk. "
    "Use only these types: procedure, diagnostic_rule, constraint, tool_instruction, "
    "success_criterion, failure_pattern, dependency, permission. "
    "Return only units supported by the chunk."
)


class ExtractedUnit(BaseModel):
    """One unit proposed by the model. Source refs are attached later."""

    model_config = ConfigDict(extra="forbid")

    type: KnowledgeUnitType
    title: str
    trigger: str = ""
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    safety_constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ChunkExtraction(BaseModel):
    """Structured output for a single chunk."""

    model_config = ConfigDict(extra="forbid")

    units: list[ExtractedUnit] = Field(default_factory=list)


class _Draft:
    def __init__(self, unit: ExtractedUnit, source_ref: dict[str, object]) -> None:
        self.type = unit.type
        self.title = unit.title.strip()
        self.trigger = unit.trigger.strip()
        self.preconditions = list(unit.preconditions)
        self.steps = list(unit.steps)
        self.safety_constraints = list(unit.safety_constraints)
        self.success_criteria = list(unit.success_criteria)
        self.confidence = unit.confidence
        self.source_refs = [source_ref]


async def extract_document(
    db_path: Path,
    document_id: str,
    gateway: ModelGateway,
    *,
    index: RetrievalIndex | None = None,
) -> list[KnowledgeUnit]:
    """Replace a document's knowledge units, then project them into the index."""
    with connection(db_path) as conn:
        chunks = list_chunks_by_document(conn, document_id)
    drafts: list[_Draft] = []
    for chunk in chunks:
        extraction = await generate_structured(
            gateway,
            ChunkExtraction,
            run_id=f"extract_{document_id}",
            messages=[
                ChatMessage(role="system", content=_SYSTEM),
                ChatMessage(role="user", content=_chunk_prompt(chunk)),
            ],
            stage="knowledge",
        )
        for unit in extraction.units:
            drafts.append(_Draft(unit, _source_ref(document_id, chunk)))
    units = [_to_unit(document_id, draft) for draft in _merge(drafts)]
    with connection(db_path) as conn:
        delete_knowledge_units_by_document(conn, document_id)
        for unit in units:
            insert_knowledge_unit(conn, unit)
    resolved = index if index is not None else build_index(get_settings(), db_path=db_path)
    await Indexer(db_path, resolved).index_knowledge_units(document_id)
    return units


def _chunk_prompt(chunk: Chunk) -> str:
    title = chunk.title or ""
    return f"title: {title}\n\n{chunk.text}"


def _source_ref(document_id: str, chunk: Chunk) -> dict[str, object]:
    return {
        "document_id": document_id,
        "chunk_id": chunk.id,
        "page": chunk.page,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
    }


def _merge(drafts: list[_Draft]) -> list[_Draft]:
    merged: list[_Draft] = []
    by_title: dict[str, _Draft] = {}
    for draft in drafts:
        key = draft.title.casefold()
        if not key:
            merged.append(draft)
            continue
        current = by_title.get(key)
        if current is None:
            by_title[key] = draft
            merged.append(draft)
            continue
        if not current.trigger and draft.trigger:
            current.trigger = draft.trigger
        current.confidence = max(current.confidence, draft.confidence)
        current.preconditions = _union(current.preconditions, draft.preconditions)
        current.steps = _union(current.steps, draft.steps)
        current.safety_constraints = _union(current.safety_constraints, draft.safety_constraints)
        current.success_criteria = _union(current.success_criteria, draft.success_criteria)
        current.source_refs = _union_refs(current.source_refs, draft.source_refs)
    return merged


def _union(left: list[str], right: list[str]) -> list[str]:
    seen = set(left)
    combined = list(left)
    for item in right:
        if item not in seen:
            seen.add(item)
            combined.append(item)
    return combined


def _union_refs(
    left: list[dict[str, object]],
    right: list[dict[str, object]],
) -> list[dict[str, object]]:
    seen = {_ref_key(item) for item in left}
    combined = list(left)
    for item in right:
        key = _ref_key(item)
        if key not in seen:
            seen.add(key)
            combined.append(item)
    return combined


def _ref_key(item: dict[str, object]) -> tuple[object, ...]:
    names = ("document_id", "chunk_id", "page", "line_start", "line_end")
    return tuple(item.get(name) for name in names)


def _to_unit(document_id: str, draft: _Draft) -> KnowledgeUnit:
    text_parts = [draft.title]
    if draft.trigger:
        text_parts.append(draft.trigger)
    text_parts.extend(draft.steps)
    first = draft.source_refs[0]
    return KnowledgeUnit(
        id=f"ku_{uuid4().hex}",
        document_id=document_id,
        type=draft.type,
        content={
            "title": draft.title,
            "trigger": draft.trigger,
            "preconditions": draft.preconditions,
            "steps": draft.steps,
            "safety_constraints": draft.safety_constraints,
            "success_criteria": draft.success_criteria,
            "source_refs": draft.source_refs,
            "text": "\n".join(text_parts),
        },
        source_location={
            "page": first.get("page"),
            "line_start": first.get("line_start"),
            "line_end": first.get("line_end"),
            "chunk_id": first.get("chunk_id"),
        },
        confidence=draft.confidence,
    )
