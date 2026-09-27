"""Pass 8: write a skill-card and store the directory as DRAFT, then CANDIDATE."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from skillforge.compiler.validate import validate_skill_dir
from skillforge.domain.entities import SkillVersion
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.registry.service import SkillRegistry
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import TraceSink

_FILES = (
    "SKILL.md",
    "references/source-map.json",
    "scripts/diagnose.py",
    "scripts/recover.py",
    "scripts/verify.py",
    "evals/evals.json",
)


async def package_skill(
    skill_dir: Path,
    project_id: str,
    registry: SkillRegistry,
    *,
    run_id: str,
    sink: TraceSink,
    bus: EventBus,
) -> SkillVersion:
    """Store the skill as DRAFT. Promote to CANDIDATE only when static validation passes."""
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    meta, body = _frontmatter(text)
    name = str(meta.get("name") or "skill")
    version_label = str(meta.get("version") or "0.1.0")
    files = _read_files(skill_dir)
    files["skill-card.md"] = _card(meta, body, skill_dir).encode("utf-8")
    skill = registry.create_skill(project_id, name, description=_text(meta.get("description")))
    stored = registry.create_version(skill.id, version_label, files)
    result = await validate_skill_dir(skill_dir, run_id=run_id, sink=sink, bus=bus)
    if not result.passed:
        return stored
    return registry.transition(stored.id, SkillVersionStatus.CANDIDATE)


def _read_files(skill_dir: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for relative in _FILES:
        path = skill_dir / relative
        if path.is_file():
            files[relative] = path.read_bytes()
    return files


def _frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}, text
    loaded = yaml.safe_load(parts[1])
    if not isinstance(loaded, dict):
        return {}, parts[2]
    return loaded, parts[2]


def _card(meta: dict[str, object], body: str, skill_dir: Path) -> str:
    name = _text(meta.get("name")) or "skill"
    version = _text(meta.get("version")) or "0.1.0"
    description = _text(meta.get("description"))
    triggers = meta.get("triggers")
    trigger_text = ", ".join(str(item) for item in triggers) if isinstance(triggers, list) else ""
    tools = meta.get("tools")
    tool_text = ", ".join(str(item) for item in tools) if isinstance(tools, list) else ""
    steps = [line.strip() for line in body.splitlines() if line.strip().startswith("ins_")]
    eval_ids = _eval_ids(skill_dir / "evals" / "evals.json")
    lines = [
        f"# {name}",
        "",
        f"版本 {version}。{description}",
        "",
        "## 何时使用",
        "",
        trigger_text,
        "",
        "## 工具",
        "",
        tool_text,
        "",
        "## 步骤",
        "",
        *[f"- {step}" for step in steps],
        "",
        "## 评测",
        "",
        *[f"- {item}" for item in eval_ids],
        "",
    ]
    return "\n".join(lines)


def _eval_ids(path: Path) -> list[str]:
    if not path.is_file():
        return []
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        return []
    return [str(item["id"]) for item in loaded if isinstance(item, dict) and item.get("id")]


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
