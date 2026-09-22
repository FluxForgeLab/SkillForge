"""System prompt for the agent loop. Skill text is appended after the bare prompt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_BARE_PROMPT = (
    "You are the service recovery agent. Use the provided tools to handle the task. "
    "When the task is finished, reply with text and do not call tools."
)
_REFERENCE_FIELDS = ("document", "page", "sha256")


def system_prompt(skill_path: str | None) -> str:
    if skill_path is None:
        return _BARE_PROMPT
    section = _skill_section(Path(skill_path))
    return f"{_BARE_PROMPT}\n\n{section}"


def _skill_section(path: Path) -> str:
    root = _skill_root(path)
    meta, body = _load_skill(root)
    lines = ["# Skill", f"name: {_text(meta.get('name'))}"]
    description = _text(meta.get("description"))
    if description:
        lines.append(f"description: {description}")
    triggers = _triggers(meta.get("triggers"))
    if triggers:
        lines.append(f"triggers: {triggers}")
    lines.append("")
    lines.append(body)
    references = _references(root)
    if references:
        lines.append("")
        lines.append("# References")
        lines.extend(references)
    return "\n".join(lines)


def _skill_root(path: Path) -> Path:
    if path.is_dir():
        return path
    if path.name == "SKILL.md" and path.is_file():
        return path.parent
    raise ValueError(f"SKILL.md not found at {path}")


def _load_skill(root: Path) -> tuple[dict[str, Any], str]:
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError(f"SKILL.md not found in {root}")
    text = skill_md.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md is missing frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) < 3 or not parts[1].strip():
        raise ValueError("SKILL.md is missing frontmatter")
    loaded = yaml.safe_load(parts[1])
    if not isinstance(loaded, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    return loaded, parts[2].strip()


def _references(root: Path) -> list[str]:
    path = root / "references" / "source-map.json"
    if not path.is_file():
        return []
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("source-map.json must be an object")
    rows: list[str] = []
    for key in sorted(loaded):
        value = loaded[key]
        if not isinstance(value, dict) or not value:
            continue
        bits = [
            f"{field}={value[field]}"
            for field in _REFERENCE_FIELDS
            if value.get(field) not in (None, "")
        ]
        if bits:
            rows.append(f"{key}: " + " ".join(bits))
    return rows


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _triggers(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value).strip()
