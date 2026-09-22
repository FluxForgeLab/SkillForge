"""Sandbox policy model and the default restricted policy."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from skillforge.domain.errors import PolicyViolation

_DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "policies" / "default.yaml"


class NetworkPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["restricted"]
    allow: list[str]


class FilesystemPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: list[str]
    write: list[str]


class ProcessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deny: list[str]


class DangerousOperations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_approval: bool


class SandboxPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network: NetworkPolicy
    filesystem: FilesystemPolicy
    process: ProcessPolicy
    dangerous_operations: DangerousOperations

    def denied_command(self, command: str) -> str | None:
        denied = set(self.process.deny)
        for token in command.split():
            name = token.rsplit("/", 1)[-1]
            if name in denied:
                return name
            if "rm" in denied and name.startswith("rm"):
                return "rm"
        return None

    def ensure_read(self, path: str) -> None:
        normalized = _posix_path(path)
        if not _is_under(normalized, self.filesystem.read):
            raise PolicyViolation(kind="filesystem", name=path, detail="read not allowed")

    def ensure_write(self, path: str) -> None:
        normalized = _posix_path(path)
        if not _is_under(normalized, self.filesystem.write):
            raise PolicyViolation(kind="filesystem", name=path, detail="write not allowed")


def load_policy(path: Path) -> SandboxPolicy:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"sandbox policy must be a mapping: {path}")
    return SandboxPolicy.model_validate(loaded)


def load_default_policy() -> SandboxPolicy:
    return load_policy(_DEFAULT_POLICY_PATH)


def _posix_path(path: str) -> str:
    if "\\" in path or not path.startswith("/"):
        raise PolicyViolation(
            kind="filesystem",
            name=path,
            detail="path must be an absolute posix path",
        )
    parts = path.split("/")
    if any(part in {"", ".."} for part in parts[1:]):
        raise PolicyViolation(kind="filesystem", name=path, detail="path escapes policy roots")
    return path


def _is_under(path: str, roots: list[str]) -> bool:
    for root in roots:
        prefix = root.rstrip("/") or "/"
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False
