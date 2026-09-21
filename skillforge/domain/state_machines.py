"""Pipeline and SkillVersion state machines (R4: separate enums and transition tables)."""

from __future__ import annotations

from enum import StrEnum

from skillforge.domain.errors import InvalidStateTransition


class PipelineState(StrEnum):
    INGESTED = "INGESTED"
    EXTRACTED = "EXTRACTED"
    DRAFTED = "DRAFTED"
    VALIDATING = "VALIDATING"
    CANDIDATE = "CANDIDATE"
    EVALUATING = "EVALUATING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class SkillVersionStatus(StrEnum):
    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


_PIPELINE_TRANSITIONS: dict[PipelineState, frozenset[PipelineState]] = {
    PipelineState.INGESTED: frozenset({PipelineState.EXTRACTED}),
    PipelineState.EXTRACTED: frozenset({PipelineState.DRAFTED}),
    PipelineState.DRAFTED: frozenset({PipelineState.VALIDATING}),
    PipelineState.VALIDATING: frozenset({PipelineState.CANDIDATE}),
    PipelineState.CANDIDATE: frozenset({PipelineState.EVALUATING}),
    PipelineState.EVALUATING: frozenset({PipelineState.PASSED, PipelineState.FAILED}),
    PipelineState.PASSED: frozenset({PipelineState.APPROVED}),
    PipelineState.APPROVED: frozenset({PipelineState.PUBLISHED}),
    PipelineState.FAILED: frozenset(),
    PipelineState.PUBLISHED: frozenset(),
}

_SKILL_VERSION_TRANSITIONS: dict[SkillVersionStatus, frozenset[SkillVersionStatus]] = {
    SkillVersionStatus.DRAFT: frozenset(
        {SkillVersionStatus.CANDIDATE, SkillVersionStatus.REJECTED},
    ),
    SkillVersionStatus.CANDIDATE: frozenset(
        {SkillVersionStatus.VALIDATED, SkillVersionStatus.REJECTED},
    ),
    SkillVersionStatus.VALIDATED: frozenset(
        {SkillVersionStatus.APPROVED, SkillVersionStatus.REJECTED},
    ),
    SkillVersionStatus.APPROVED: frozenset({SkillVersionStatus.PUBLISHED}),
    SkillVersionStatus.PUBLISHED: frozenset(),
    SkillVersionStatus.REJECTED: frozenset(),
}


def ensure_pipeline_transition(current: PipelineState, target: PipelineState) -> None:
    """Raise InvalidStateTransition if moving from current to target is not allowed."""
    if current == target:
        raise InvalidStateTransition(
            machine="pipeline",
            current=current.value,
            target=target.value,
        )
    allowed = _PIPELINE_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransition(
            machine="pipeline",
            current=current.value,
            target=target.value,
        )


def ensure_skill_version_transition(
    current: SkillVersionStatus,
    target: SkillVersionStatus,
) -> None:
    """Raise InvalidStateTransition if moving from current to target is not allowed."""
    if current == target:
        raise InvalidStateTransition(
            machine="skill_version",
            current=current.value,
            target=target.value,
        )
    allowed = _SKILL_VERSION_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransition(
            machine="skill_version",
            current=current.value,
            target=target.value,
        )
