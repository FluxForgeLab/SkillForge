"""Skill artifact manifest and hashing."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field


class ManifestFileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    skill_name: str
    version: str
    parent_version_id: str | None = None
    created_at: datetime
    files: list[ManifestFileEntry] = Field(default_factory=list)


def skill_key_from_name(name: str) -> str:
    key = name.strip().lower()
    key = re.sub(r"[^\w\s-]", "", key, flags=re.UNICODE)
    key = re.sub(r"[\s_]+", "-", key)
    key = key.strip("-")
    return key or "skill"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def manifest_json_bytes(manifest: SkillManifest) -> bytes:
    payload = manifest.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8",
    )


def write_manifest(version_dir: Path, manifest: SkillManifest) -> str:
    """Write manifest.json and return manifest_hash (sha256 of file bytes)."""
    version_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = version_dir / "manifest.json"
    body = manifest_json_bytes(manifest)
    manifest_path.write_bytes(body)
    return sha256_bytes(body)


def artifact_path_for(skill_key: str, version: str, *, prefix: str = "skills/generated") -> str:
    return PurePosixPath(prefix) / skill_key / version
