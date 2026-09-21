"""Filesystem storage for generated skill versions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from skillforge.registry.manifest import (
    ManifestFileEntry,
    SkillManifest,
    artifact_path_for,
    sha256_bytes,
    skill_key_from_name,
    write_manifest,
)


class ArtifactStore:
    def __init__(self, generated_root: Path, *, path_prefix: str = "skills/generated") -> None:
        self._root = generated_root
        self._path_prefix = path_prefix

    def write_version(
        self,
        *,
        skill_id: str,
        skill_name: str,
        version: str,
        parent_version_id: str | None,
        files: Mapping[str, bytes],
    ) -> tuple[str, str]:
        skill_key = skill_key_from_name(skill_name)
        version_dir = self._root / skill_key / version
        version_dir.mkdir(parents=True, exist_ok=True)

        entries: list[ManifestFileEntry] = []
        for relative_path in sorted(files.keys(), key=lambda p: PurePosixPath(p).as_posix()):
            normalized = PurePosixPath(relative_path).as_posix()
            if normalized.startswith("..") or normalized.startswith("/"):
                msg = f"invalid artifact path: {relative_path!r}"
                raise ValueError(msg)
            target = version_dir / normalized
            target.parent.mkdir(parents=True, exist_ok=True)
            content = files[relative_path]
            target.write_bytes(content)
            entries.append(
                ManifestFileEntry(path=normalized, sha256=sha256_bytes(content)),
            )

        manifest = SkillManifest(
            skill_id=skill_id,
            skill_name=skill_name,
            version=version,
            parent_version_id=parent_version_id,
            created_at=datetime.now(UTC),
            files=entries,
        )
        manifest_hash = write_manifest(version_dir, manifest)
        artifact_path = artifact_path_for(skill_key, version, prefix=self._path_prefix).as_posix()
        return artifact_path, manifest_hash
