"""Load a §8.4 SkillSpec and reject tools or permissions outside the landed limits."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from skillforge.domain.entities import SkillSpec
from skillforge.domain.errors import PolicyViolation, SkillForgeError
from skillforge.runtime.tools.opslab import runtime_tools
from skillforge.sandbox.policy import load_default_policy


class SkillSpecError(SkillForgeError):
    """Raised when a SkillSpec names an unknown tool or grants more than the default policy."""


def load_skill_spec(source: str | Path | Mapping[str, Any]) -> SkillSpec:
    """Parse YAML or a mapping, then apply registry and policy checks."""
    loaded = _coerce(source)
    spec = SkillSpec.model_validate(loaded)
    return validate_skill_spec(spec)


def validate_skill_spec(spec: SkillSpec) -> SkillSpec:
    """Reject unknown tools and any permission wider than the default sandbox policy."""
    _require_tools(spec.tools)
    policy = load_default_policy()
    permissions = spec.permissions
    _require_paths(permissions.filesystem.read, policy.ensure_read)
    _require_paths(permissions.filesystem.write, policy.ensure_write)
    allowed = set(policy.network.allow)
    for host in permissions.network.allow:
        if host not in allowed:
            raise SkillSpecError(f"network allow {host!r} is outside the default policy")
    if permissions.shell.destructive_commands:
        raise SkillSpecError("shell.destructive_commands must be false")
    return spec


def _require_tools(tools: list[str]) -> None:
    known = {item.name for item in runtime_tools().specs()}
    seen: set[str] = set()
    for tool in tools:
        if tool in seen:
            raise SkillSpecError(f"duplicate tool {tool!r}")
        seen.add(tool)
        if tool not in known:
            raise SkillSpecError(f"unknown tool {tool!r}")


def _require_paths(paths: list[str], check: Callable[[str], None]) -> None:
    for path in paths:
        try:
            check(path)
        except PolicyViolation as exc:
            raise SkillSpecError(str(exc)) from exc


def _coerce(source: str | Path | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(source, Mapping) and not isinstance(source, str):
        return source
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8")
    elif isinstance(source, str):
        path = Path(source)
        text = path.read_text(encoding="utf-8") if path.is_file() else source
    else:
        raise SkillSpecError("SkillSpec source must be a mapping, path, or YAML text")
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise SkillSpecError("SkillSpec YAML must be a mapping")
    return loaded
