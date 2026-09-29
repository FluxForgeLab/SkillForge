"""Human-only SkillVersion approve / publish (never called from evolution)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from skillforge.db.connection import connection
from skillforge.db.repositories.skills import get_skill
from skillforge.domain.entities import SkillVersion
from skillforge.domain.errors import InvalidStateTransition
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.registry.errors import (
    MissingApproverError,
    PublishPathOccupiedError,
    SkillNotFoundError,
)
from skillforge.registry.manifest import skill_key_from_name
from skillforge.registry.service import SkillRegistry

_APPROVER_FILENAME = "approver.txt"


@dataclass(frozen=True, slots=True)
class ApproveResult:
    """Outcome of a human approve; carries approver for C7.7 display."""

    version: SkillVersion
    approver: str


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Outcome of a human publish; includes destination path."""

    version: SkillVersion
    published_path: Path


def approve(registry: SkillRegistry, version_id: str, approver: str) -> ApproveResult:
    """Require a non-empty approver; CANDIDATE → VALIDATED → APPROVED.

    Writes ``approver.txt`` into the version artifact directory. Does not add
    a schema column; persistence for later API display is the returned object
    plus that file.
    """
    name = approver.strip() if isinstance(approver, str) else ""
    if not name:
        raise MissingApproverError(version_id)

    current = registry.get_version(version_id)
    if current.status == SkillVersionStatus.CANDIDATE:
        registry.transition(version_id, SkillVersionStatus.VALIDATED)
        updated = registry.transition(version_id, SkillVersionStatus.APPROVED)
    elif current.status == SkillVersionStatus.VALIDATED:
        updated = registry.transition(version_id, SkillVersionStatus.APPROVED)
    else:
        raise InvalidStateTransition(
            machine="skill_version",
            current=current.status.value,
            target=SkillVersionStatus.APPROVED.value,
        )

    artifact_dir = registry.artifact_dir(version_id)
    (artifact_dir / _APPROVER_FILENAME).write_text(name + "\n", encoding="utf-8")

    return ApproveResult(version=updated, approver=name)


def publish(
    registry: SkillRegistry,
    version_id: str,
    *,
    published_root: Path | None = None,
) -> PublishResult:
    """Copy APPROVED artifacts to published_dir / skill_key / version, then PUBLISHED."""
    version = registry.get_version(version_id)
    if version.status != SkillVersionStatus.APPROVED:
        raise InvalidStateTransition(
            machine="skill_version",
            current=version.status.value,
            target=SkillVersionStatus.PUBLISHED.value,
        )

    root = published_root if published_root is not None else registry.published_root

    with connection(registry.db_path) as conn:
        skill = get_skill(conn, version.skill_id)
    if skill is None:
        raise SkillNotFoundError(version.skill_id)

    skill_key = skill_key_from_name(skill.name)
    src = registry.artifact_dir(version_id)
    # skill.id keeps two skills that share a display name from overwriting each other.
    dest = root / skill_key / skill.id / version.version
    if dest.exists():
        raise PublishPathOccupiedError(skill.name, version.version, dest.as_posix())
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)

    updated = registry.transition(version_id, SkillVersionStatus.PUBLISHED)
    return PublishResult(version=updated, published_path=dest)
