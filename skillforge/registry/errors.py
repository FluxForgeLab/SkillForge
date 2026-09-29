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


class PublishPathOccupiedError(RegistryError):
    """Another skill already owns this published name and version."""

    def __init__(self, skill_name: str, version: str, path: str) -> None:
        self.skill_name = skill_name
        self.version = version
        self.path = path
        super().__init__(
            f"发布目录已被占用：{path}。同名技能「{skill_name}」的版本 {version} "
            "已经发布过。请更换技能名称或版本号后再发布，系统不会覆盖已有目录。"
        )


class MissingApproverError(RegistryError):
    """approve() requires a non-empty approver string."""

    def __init__(self, version_id: str) -> None:
        self.version_id = version_id
        super().__init__(f"approver required to approve skill version {version_id!r}")
