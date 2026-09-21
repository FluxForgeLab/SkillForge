"""C2.2: Domain model validation against architecture examples."""

from __future__ import annotations

from datetime import UTC, datetime

from skillforge.domain import (
    EvalCase,
    Failure,
    FailureClass,
    KnowledgeUnit,
    KnowledgeUnitType,
    SkillSpec,
    SkillVersion,
    SkillVersionStatus,
    transition_skill_version,
)


def test_eval_case_from_section_8_10() -> None:
    case = EvalCase.model_validate(
        {
            "id": "eval_nginx_001",
            "name": "backend process stopped",
            "task": "Restore the web service and verify recovery.",
            "fixture": "backend_stopped",
            "expected": {
                "http_status": 200,
                "backend_running": True,
            },
            "forbidden": ["delete_volume", "restart_database"],
            "timeout_sec": 180,
        },
    )
    assert case.fixture == "backend_stopped"
    assert case.expected["http_status"] == 200


def test_failure_from_section_8_12() -> None:
    failure = Failure.model_validate(
        {
            "run_id": "run_104",
            "class": "missing_instruction",
            "symptom": "agent restarted backend but did not inspect nginx upstream",
            "failed_assertion": "health endpoint still returned 502",
            "evidence": [
                "nginx upstream points to :8081",
                "backend listens on :8080",
            ],
            "suspected_skill_gap": "No instruction to verify reverse proxy upstream",
            "source_support": ["doc_xxx#page=15"],
        },
    )
    assert failure.failure_class == FailureClass.MISSING_INSTRUCTION


def test_knowledge_unit_diagnostic_rule() -> None:
    ku = KnowledgeUnit(
        id="ku_001",
        document_id="doc_xxx",
        type=KnowledgeUnitType.DIAGNOSTIC_RULE,
        content={"title": "Appendix B", "trigger": "502 upstream"},
        confidence=0.9,
    )
    assert ku.type == KnowledgeUnitType.DIAGNOSTIC_RULE


def test_skill_spec_placeholder() -> None:
    spec = SkillSpec.model_validate(
        {
            "name": "service-recovery",
            "description": "Diagnose and recover containerized web services.",
            "triggers": ["HTTP 502"],
            "tools": ["docker.inspect"],
            "permissions": {"network": {"allow": ["localhost"]}},
            "sources": ["doc_xxx"],
        },
    )
    assert spec.name == "service-recovery"


def test_transition_skill_version_returns_updated_copy() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    version = SkillVersion(
        id="sv_1",
        skill_id="skill_1",
        version="0.1",
        status=SkillVersionStatus.DRAFT,
        created_at=created,
    )
    updated = transition_skill_version(version, SkillVersionStatus.CANDIDATE)
    assert updated.status == SkillVersionStatus.CANDIDATE
    assert version.status == SkillVersionStatus.DRAFT
