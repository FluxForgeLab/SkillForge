"""C2.2: Pipeline and SkillVersion transition tables."""

from __future__ import annotations

import pytest

from skillforge.domain import (
    InvalidStateTransition,
    PipelineState,
    SkillVersionStatus,
    ensure_pipeline_transition,
    ensure_skill_version_transition,
)

_PIPELINE_LEGAL: list[tuple[PipelineState, PipelineState]] = [
    (PipelineState.INGESTED, PipelineState.EXTRACTED),
    (PipelineState.EXTRACTED, PipelineState.DRAFTED),
    (PipelineState.DRAFTED, PipelineState.VALIDATING),
    (PipelineState.VALIDATING, PipelineState.CANDIDATE),
    (PipelineState.CANDIDATE, PipelineState.EVALUATING),
    (PipelineState.EVALUATING, PipelineState.PASSED),
    (PipelineState.EVALUATING, PipelineState.FAILED),
    (PipelineState.PASSED, PipelineState.APPROVED),
    (PipelineState.APPROVED, PipelineState.PUBLISHED),
]

_SKILL_VERSION_LEGAL: list[tuple[SkillVersionStatus, SkillVersionStatus]] = [
    (SkillVersionStatus.DRAFT, SkillVersionStatus.CANDIDATE),
    (SkillVersionStatus.DRAFT, SkillVersionStatus.REJECTED),
    (SkillVersionStatus.CANDIDATE, SkillVersionStatus.VALIDATED),
    (SkillVersionStatus.CANDIDATE, SkillVersionStatus.REJECTED),
    (SkillVersionStatus.VALIDATED, SkillVersionStatus.APPROVED),
    (SkillVersionStatus.VALIDATED, SkillVersionStatus.REJECTED),
    (SkillVersionStatus.APPROVED, SkillVersionStatus.PUBLISHED),
]


@pytest.mark.parametrize(("current", "target"), _PIPELINE_LEGAL)
def test_pipeline_legal_transitions(current: PipelineState, target: PipelineState) -> None:
    ensure_pipeline_transition(current, target)


@pytest.mark.parametrize(("current", "target"), _SKILL_VERSION_LEGAL)
def test_skill_version_legal_transitions(
    current: SkillVersionStatus,
    target: SkillVersionStatus,
) -> None:
    ensure_skill_version_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PipelineState.FAILED, PipelineState.APPROVED),
        (PipelineState.PUBLISHED, PipelineState.INGESTED),
        (PipelineState.INGESTED, PipelineState.PUBLISHED),
    ],
)
def test_pipeline_illegal_transitions(current: PipelineState, target: PipelineState) -> None:
    with pytest.raises(InvalidStateTransition) as exc_info:
        ensure_pipeline_transition(current, target)
    assert exc_info.value.machine == "pipeline"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (SkillVersionStatus.DRAFT, SkillVersionStatus.PUBLISHED),
        (SkillVersionStatus.CANDIDATE, SkillVersionStatus.APPROVED),
        (SkillVersionStatus.PUBLISHED, SkillVersionStatus.DRAFT),
        (SkillVersionStatus.REJECTED, SkillVersionStatus.DRAFT),
    ],
)
def test_skill_version_illegal_transitions(
    current: SkillVersionStatus,
    target: SkillVersionStatus,
) -> None:
    with pytest.raises(InvalidStateTransition) as exc_info:
        ensure_skill_version_transition(current, target)
    assert exc_info.value.machine == "skill_version"


def test_pipeline_same_state_rejected() -> None:
    with pytest.raises(InvalidStateTransition):
        ensure_pipeline_transition(PipelineState.INGESTED, PipelineState.INGESTED)


def test_skill_version_same_state_rejected() -> None:
    with pytest.raises(InvalidStateTransition):
        ensure_skill_version_transition(SkillVersionStatus.DRAFT, SkillVersionStatus.DRAFT)


def test_pipeline_terminal_states_have_no_outbound() -> None:
    for target in PipelineState:
        with pytest.raises(InvalidStateTransition):
            ensure_pipeline_transition(PipelineState.FAILED, target)
        with pytest.raises(InvalidStateTransition):
            ensure_pipeline_transition(PipelineState.PUBLISHED, target)
