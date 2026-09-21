"""Pydantic domain entities aligned with architecture §9 and §8.x."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from skillforge.domain.enums import (
    EvaluationRunStatus,
    FailureClass,
    KnowledgeUnitType,
    TraceEventType,
)
from skillforge.domain.state_machines import SkillVersionStatus, ensure_skill_version_transition


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str | None = None
    created_at: datetime


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    filename: str
    sha256: str
    version: str
    parser: str
    created_at: datetime


class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    document_id: str
    project_id: str
    ordinal: int
    text: str
    title: str | None = None
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None


class KnowledgeUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    document_id: str
    type: KnowledgeUnitType
    content: dict[str, Any]
    source_location: dict[str, Any] | None = None
    confidence: float | None = None


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    name: str
    description: str | None = None
    current_version_id: str | None = None


class SkillVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    skill_id: str
    version: str
    parent_version_id: str | None = None
    status: SkillVersionStatus
    artifact_path: str | None = None
    manifest_hash: str | None = None
    created_at: datetime


def transition_skill_version(
    version: SkillVersion,
    target: SkillVersionStatus,
) -> SkillVersion:
    """Return a copy of version with status updated after validating the transition."""
    ensure_skill_version_transition(version.status, target)
    return version.model_copy(update={"status": target})


class EvalCase(BaseModel):
    """Matches evals.json (§8.10); DB table omits name/timeout_sec until repositories map them."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    task: str
    fixture: str
    expected: dict[str, Any]
    forbidden: list[str] = Field(default_factory=list)
    timeout_sec: int = 180
    skill_id: str | None = None


class EvaluationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    skill_version_id: str
    baseline: dict[str, Any]
    metrics: dict[str, Any]
    status: EvaluationRunStatus
    started_at: datetime
    finished_at: datetime | None = None


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    type: TraceEventType
    timestamp: datetime
    stage: str | None = None
    name: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None


class Failure(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: str
    failure_class: FailureClass = Field(alias="class")
    symptom: str
    failed_assertion: str | None = None
    evidence: list[str] = Field(default_factory=list)
    suspected_skill_gap: str | None = None
    source_support: list[str] = Field(default_factory=list)


class PatchProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diff: str
    summary: str | None = None
    target_skill_version_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class SkillSpec(BaseModel):
    """Placeholder IR for Compiler (§8.4); full validation in C6.1."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    triggers: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    permissions: dict[str, Any] = Field(default_factory=dict)
    success: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
