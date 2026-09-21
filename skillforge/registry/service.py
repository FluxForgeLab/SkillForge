"""Skill registry: SQLite records plus generated artifact tree."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from skillforge.config import Settings, get_settings
from skillforge.db.connection import connection
from skillforge.db.repositories.skill_versions import (
    find_skill_version_by_label,
    get_skill_version,
    insert_skill_version,
    list_skill_versions,
    update_skill_version_status,
)
from skillforge.db.repositories.skills import (
    get_skill,
    insert_skill,
    update_skill_current_version,
)
from skillforge.domain.entities import Skill, SkillVersion, transition_skill_version
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.registry.errors import (
    DuplicateSkillVersionError,
    ParentVersionMismatchError,
    SkillNotFoundError,
    SkillVersionNotFoundError,
)
from skillforge.registry.store import ArtifactStore


class SkillRegistry:
    def __init__(
        self,
        db_path: Path,
        *,
        generated_root: Path | None = None,
        path_prefix: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        resolved_settings = settings if settings is not None else get_settings()
        self._db_path = db_path
        prefix = path_prefix or resolved_settings.skills_generated_dir.as_posix()
        root = (
            generated_root if generated_root is not None else resolved_settings.skills_generated_dir
        )
        self._store = ArtifactStore(root, path_prefix=prefix)

    def create_skill(
        self,
        project_id: str,
        name: str,
        *,
        description: str | None = None,
    ) -> Skill:
        skill = Skill(
            id=f"skill_{uuid4().hex}",
            project_id=project_id,
            name=name,
            description=description,
            current_version_id=None,
        )
        with connection(self._db_path) as conn:
            insert_skill(conn, skill)
        return skill

    def create_version(
        self,
        skill_id: str,
        version: str,
        files: Mapping[str, bytes],
        *,
        parent_version_id: str | None = None,
        initial_status: SkillVersionStatus = SkillVersionStatus.DRAFT,
    ) -> SkillVersion:
        with connection(self._db_path) as conn:
            skill = get_skill(conn, skill_id)
            if skill is None:
                raise SkillNotFoundError(skill_id)

            if find_skill_version_by_label(conn, skill_id, version) is not None:
                raise DuplicateSkillVersionError(skill_id, version)

            if parent_version_id is not None:
                parent = get_skill_version(conn, parent_version_id)
                if parent is None:
                    raise SkillVersionNotFoundError(parent_version_id)
                if parent.skill_id != skill_id:
                    raise ParentVersionMismatchError(skill_id, parent_version_id)

        artifact_path, manifest_hash = self._store.write_version(
            skill_id=skill_id,
            skill_name=skill.name,
            version=version,
            parent_version_id=parent_version_id,
            files=files,
        )

        created_at = datetime.now(UTC)
        skill_version = SkillVersion(
            id=f"sv_{uuid4().hex}",
            skill_id=skill_id,
            version=version,
            parent_version_id=parent_version_id,
            status=initial_status,
            artifact_path=artifact_path,
            manifest_hash=manifest_hash,
            created_at=created_at,
        )

        with connection(self._db_path) as conn:
            insert_skill_version(conn, skill_version)
            update_skill_current_version(conn, skill_id, skill_version.id)

        return skill_version

    def get_version(self, version_id: str) -> SkillVersion:
        with connection(self._db_path) as conn:
            version = get_skill_version(conn, version_id)
        if version is None:
            raise SkillVersionNotFoundError(version_id)
        return version

    def list_versions(self, skill_id: str) -> list[SkillVersion]:
        with connection(self._db_path) as conn:
            return list_skill_versions(conn, skill_id)

    def transition(self, version_id: str, target: SkillVersionStatus) -> SkillVersion:
        with connection(self._db_path) as conn:
            current = get_skill_version(conn, version_id)
            if current is None:
                raise SkillVersionNotFoundError(version_id)
            updated = transition_skill_version(current, target)
            update_skill_version_status(conn, version_id, updated.status)
        return updated
