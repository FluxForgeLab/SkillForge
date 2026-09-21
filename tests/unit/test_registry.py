"""C2.7: Skill registry artifact store and version transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from skillforge.config import Settings
from skillforge.db import initialize_database
from skillforge.db.connection import connection
from skillforge.db.repositories.projects import insert_project
from skillforge.domain import InvalidStateTransition
from skillforge.domain.entities import Project, SkillVersionStatus
from skillforge.registry import (
    DuplicateSkillVersionError,
    ParentVersionMismatchError,
    SkillRegistry,
)
from skillforge.registry.manifest import sha256_file


def _make_registry(tmp_path: Path) -> tuple[SkillRegistry, str]:
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
    settings = Settings(_env_file=None)
    registry = SkillRegistry(
        db_path,
        generated_root=tmp_path / "generated",
        path_prefix=settings.skills_generated_dir.as_posix(),
        settings=settings,
    )
    return registry, project_id


def _minimal_files() -> dict[str, bytes]:
    return {
        "SKILL.md": b"---\nname: demo\n---\n# Demo\n",
        "evals/evals.json": b"[]",
    }


def test_create_v01_writes_manifest_and_db(tmp_path: Path) -> None:
    registry, project_id = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "Service Recovery")
    version = registry.create_version(skill.id, "0.1", _minimal_files())

    assert version.parent_version_id is None
    assert version.status == SkillVersionStatus.DRAFT
    assert version.manifest_hash
    assert version.artifact_path == "skills/generated/service-recovery/0.1"

    manifest_path = tmp_path / "generated" / "service-recovery" / "0.1" / "manifest.json"
    assert manifest_path.is_file()
    assert sha256_file(manifest_path) == version.manifest_hash


def test_create_v02_sets_parent(tmp_path: Path) -> None:
    registry, project_id = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "service-recovery")
    v01 = registry.create_version(skill.id, "0.1", _minimal_files())
    v02 = registry.create_version(
        skill.id,
        "0.2",
        _minimal_files(),
        parent_version_id=v01.id,
    )

    assert v02.parent_version_id == v01.id
    versions = registry.list_versions(skill.id)
    assert [v.version for v in versions] == ["0.1", "0.2"]
    assert skill.id == v01.skill_id == v02.skill_id


def test_duplicate_version_rejected(tmp_path: Path) -> None:
    registry, project_id = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "dup-skill")
    registry.create_version(skill.id, "0.1", _minimal_files())

    with pytest.raises(DuplicateSkillVersionError):
        registry.create_version(skill.id, "0.1", _minimal_files())


def test_parent_must_belong_to_same_skill(tmp_path: Path) -> None:
    registry, project_id = _make_registry(tmp_path)
    skill_a = registry.create_skill(project_id, "skill-a")
    skill_b = registry.create_skill(project_id, "skill-b")
    v01 = registry.create_version(skill_a.id, "0.1", _minimal_files())

    with pytest.raises(ParentVersionMismatchError):
        registry.create_version(
            skill_b.id,
            "0.1",
            _minimal_files(),
            parent_version_id=v01.id,
        )


def test_illegal_publish_transition(tmp_path: Path) -> None:
    registry, project_id = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "publish-skill")
    version = registry.create_version(skill.id, "0.1", _minimal_files())

    with pytest.raises(InvalidStateTransition):
        registry.transition(version.id, SkillVersionStatus.PUBLISHED)


def test_legal_transition_updates_status(tmp_path: Path) -> None:
    registry, project_id = _make_registry(tmp_path)
    skill = registry.create_skill(project_id, "transition-skill")
    version = registry.create_version(skill.id, "0.1", _minimal_files())

    updated = registry.transition(version.id, SkillVersionStatus.CANDIDATE)
    assert updated.status == SkillVersionStatus.CANDIDATE
    assert registry.get_version(version.id).status == SkillVersionStatus.CANDIDATE
