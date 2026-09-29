"""C7.6: human-only approve / publish; evolution stops at CANDIDATE."""

from __future__ import annotations

import ast
import difflib
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from skillforge.config import Settings
from skillforge.db import initialize_database
from skillforge.db.connection import connection
from skillforge.db.repositories.projects import insert_project
from skillforge.domain import InvalidStateTransition
from skillforge.domain.entities import PatchProposal, Project, SkillVersionStatus
from skillforge.evolution.apply import apply_patch
from skillforge.registry import (
    MissingApproverError,
    PublishPathOccupiedError,
    SkillRegistry,
    approve,
    publish,
)

_EVOLUTION_ROOT = Path(__file__).resolve().parents[2] / "skillforge" / "evolution"
_FORBIDDEN_FN = frozenset({"approve", "publish"})
_CALL_OR_IMPORT = re.compile(
    r"(?:^|\W)(?:approve|publish)\s*\(|from\s+skillforge\.registry\.human\b"
    r"|import\s+skillforge\.registry\.human\b",
)


def _make_registry(tmp_path: Path) -> tuple[SkillRegistry, str, Path]:
    db_path = tmp_path / "registry.db"
    initialize_database(db_path)
    project_id = f"proj_{uuid4().hex}"
    with connection(db_path) as conn:
        insert_project(
            conn,
            Project(
                id=project_id,
                name="Demo Project",
                description=None,
                created_at=datetime.now(UTC),
            ),
        )
    published = tmp_path / "published"
    settings = Settings(_env_file=None, skills_published_dir=published)
    registry = SkillRegistry(
        db_path,
        generated_root=tmp_path / "generated",
        published_root=published,
        path_prefix=settings.skills_generated_dir.as_posix(),
        settings=settings,
    )
    return registry, project_id, published


def _minimal_files() -> dict[str, bytes]:
    return {
        "SKILL.md": b"---\nname: demo\n---\n# Demo\n",
        "evals/evals.json": b"[]",
        "scripts/check.sh": b"#!/bin/sh\necho ok\n",
    }


def _to_candidate(registry: SkillRegistry, version_id: str) -> None:
    registry.transition(version_id, SkillVersionStatus.CANDIDATE)


def test_approve_without_approver_fails(tmp_path: Path) -> None:
    registry, project_id, _ = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "needs-approver")
    version = registry.create_version(skill.id, "0.1", _minimal_files())
    _to_candidate(registry, version.id)

    with pytest.raises(MissingApproverError):
        approve(registry, version.id, "")
    with pytest.raises(MissingApproverError):
        approve(registry, version.id, "   ")


def test_approve_from_candidate_ends_approved(tmp_path: Path) -> None:
    registry, project_id, _ = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "Service Recovery")
    version = registry.create_version(skill.id, "0.1", _minimal_files())
    _to_candidate(registry, version.id)

    result = approve(registry, version.id, "alice@example.com")

    assert result.approver == "alice@example.com"
    assert result.version.status == SkillVersionStatus.APPROVED
    assert registry.get_version(version.id).status == SkillVersionStatus.APPROVED
    approver_file = registry.artifact_dir(version.id) / "approver.txt"
    assert approver_file.read_text(encoding="utf-8").strip() == "alice@example.com"


def test_publish_copies_files_and_ends_published(tmp_path: Path) -> None:
    registry, project_id, published = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "Service Recovery")
    version = registry.create_version(skill.id, "0.1", _minimal_files())
    _to_candidate(registry, version.id)
    approve(registry, version.id, "bob")

    result = publish(registry, version.id)

    assert result.version.status == SkillVersionStatus.PUBLISHED
    assert registry.get_version(version.id).status == SkillVersionStatus.PUBLISHED
    dest = published / "service-recovery" / skill.id / "0.1"
    assert result.published_path == dest
    assert (dest / "SKILL.md").is_file()
    assert (dest / "scripts" / "check.sh").is_file()
    assert (dest / "approver.txt").read_text(encoding="utf-8").strip() == "bob"


def test_publish_same_name_uses_separate_skill_directories(tmp_path: Path) -> None:
    registry, project_id, published = _make_registry(tmp_path)
    first = registry.create_skill(project_id, "Service Recovery")
    second = registry.create_skill(project_id, "Service Recovery")
    for skill in (first, second):
        version = registry.create_version(skill.id, "0.1", _minimal_files())
        _to_candidate(registry, version.id)
        approve(registry, version.id, "bob")
        publish(registry, version.id)
    assert (published / "service-recovery" / first.id / "0.1" / "SKILL.md").is_file()
    assert (published / "service-recovery" / second.id / "0.1" / "SKILL.md").is_file()


def test_publish_refuses_to_overwrite_an_existing_directory(tmp_path: Path) -> None:
    registry, project_id, published = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "Service Recovery")
    version = registry.create_version(skill.id, "0.1", _minimal_files())
    _to_candidate(registry, version.id)
    approve(registry, version.id, "bob")
    dest = published / "service-recovery" / skill.id / "0.1"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("already published\n", encoding="utf-8")

    with pytest.raises(PublishPathOccupiedError, match="发布目录已被占用"):
        publish(registry, version.id)
    assert registry.get_version(version.id).status == SkillVersionStatus.APPROVED
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "already published\n"


def test_publish_from_candidate_fails(tmp_path: Path) -> None:
    registry, project_id, _ = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "not-ready")
    version = registry.create_version(skill.id, "0.1", _minimal_files())
    _to_candidate(registry, version.id)

    with pytest.raises(InvalidStateTransition):
        publish(registry, version.id)
    assert registry.get_version(version.id).status == SkillVersionStatus.CANDIDATE


def test_create_version_and_apply_patch_stay_at_most_candidate(tmp_path: Path) -> None:
    registry, project_id, _ = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "evo-cap")
    parent = registry.create_version(skill.id, "0.1", _minimal_files())
    assert parent.status == SkillVersionStatus.DRAFT
    assert parent.status not in {
        SkillVersionStatus.APPROVED,
        SkillVersionStatus.PUBLISHED,
    }

    parent_dir = registry.artifact_dir(parent.id)
    skill_md = (parent_dir / "SKILL.md").read_text(encoding="utf-8")
    new_md = skill_md + "\nins_99 extra step.\n"
    diff = "".join(
        difflib.unified_diff(
            skill_md.splitlines(keepends=True),
            new_md.splitlines(keepends=True),
            fromfile="a/SKILL.md",
            tofile="b/SKILL.md",
        ),
    )
    created = apply_patch(
        registry,
        parent_version_id=parent.id,
        parent_dir=parent_dir,
        proposal=PatchProposal(
            diff=diff,
            summary="add step",
            target_skill_version_id=parent.id,
            evidence_refs=["trace"],
        ),
        source_map_updates={
            "ins_99": {
                "knowledge_unit_id": "ku_x",
                "document": "runbook.md",
                "sha256": "deadbeef",
                "line_start": 1,
            },
        },
        version="0.2",
    )
    assert created.status in {SkillVersionStatus.DRAFT, SkillVersionStatus.CANDIDATE}
    assert created.status not in {
        SkillVersionStatus.APPROVED,
        SkillVersionStatus.PUBLISHED,
        SkillVersionStatus.VALIDATED,
    }


def test_evolution_package_does_not_reference_approve_or_publish() -> None:
    """Static check: evolution must not call human approve/publish helpers."""
    assert _EVOLUTION_ROOT.is_dir()
    for path in sorted(_EVOLUTION_ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "skillforge.registry.human" not in source, path.name
        for match in _CALL_OR_IMPORT.finditer(source):
            pytest.fail(f"{path.name} references approve/publish: {match.group(0)!r}")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names}
                assert not (names & _FORBIDDEN_FN), path.name
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in _FORBIDDEN_FN:
                    pytest.fail(f"{path.name} calls {func.id}()")
                if isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN_FN:
                    pytest.fail(f"{path.name} calls .{func.attr}()")
