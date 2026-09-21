"""Registry errors."""

from __future__ import annotations

from skillforge.domain.errors import SkillForgeError


class RegistryError(SkillForgeError):
    """Base error for skill registry operations."""


class DuplicateSkillVersionError(RegistryError):
    """Skill already has a version with the same label."""

    def __init__(self, skill_id: str, version: str) -> None:
        self.skill_id = skill_id
        self.version = version
        super().__init__(f"skill {skill_id!r} already has version {version!r}")


class ParentVersionMismatchError(RegistryError):
    """Parent version does not belong to the same skill."""

    def __init__(self, skill_id: str, parent_version_id: str) -> None:
        self.skill_id = skill_id
        self.parent_version_id = parent_version_id
        super().__init__(
            f"parent version {parent_version_id!r} does not belong to skill {skill_id!r}",
        )


class SkillNotFoundError(RegistryError):
    def __init__(self, skill_id: str) -> None:
        self.skill_id = skill_id
        super().__init__(f"skill not found: {skill_id!r}")


class SkillVersionNotFoundError(RegistryError):
    def __init__(self, version_id: str) -> None:
        self.version_id = version_id
        super().__init__(f"skill version not found: {version_id!r}")
