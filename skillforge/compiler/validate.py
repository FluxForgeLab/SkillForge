"""Pass 7: static checks for one skill directory, then emit validation_result."""

from __future__ import annotations

import json
import py_compile
import re
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from skillforge.compiler.spec import SkillSpecError, validate_skill_spec
from skillforge.domain.entities import SkillSpec
from skillforge.domain.enums import TraceEventType
from skillforge.tracing.bus import EventBus
from skillforge.tracing.emitter import emit
from skillforge.tracing.sink import TraceSink

_INS = re.compile(r"ins_\d+")
_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ALLOWED_PATHS = frozenset(
    {
        "SKILL.md",
        "skill-card.md",
        "manifest.json",
        "approver.txt",
        "scripts",
        "references",
        "assets",
        "evals",
    }
)
_BANNED = (
    re.compile(r"\bsudo\b"),
    re.compile(r"rm -rf"),
    re.compile(r"import subprocess\b"),
    re.compile(r"import docker\b"),
    re.compile(r"\bos\.system\b"),
    re.compile(r"\beval\("),
    re.compile(r"\bexec\("),
)
_SCRIPTS = ("diagnose.py", "recover.py", "verify.py")


class ValidationResult(BaseModel):
    """Static validation outcome. Failure is a result, not an exception."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    errors: list[str] = Field(default_factory=list)


async def validate_skill_dir(
    skill_dir: Path,
    *,
    run_id: str,
    sink: TraceSink,
    bus: EventBus,
) -> ValidationResult:
    """Check frontmatter, source-map coverage, banned commands, permissions, and scripts."""
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8").replace("\r\n", "\n") if skill_md.is_file() else ""
    frontmatter, body = _split(text)
    if frontmatter is None:
        errors.append("SKILL.md is missing frontmatter")
    else:
        errors.extend(_frontmatter(frontmatter))
        errors.extend(_nvidia_frontmatter(frontmatter))
    errors.extend(_nvidia_layout(skill_dir))
    errors.extend(_coverage(body, skill_dir / "references" / "source-map.json"))
    errors.extend(_banned(_procedure(body)))
    for name in _SCRIPTS:
        errors.extend(_script(skill_dir / "scripts" / name))
    result = ValidationResult(passed=not errors, errors=errors)
    await emit(
        run_id,
        TraceEventType.VALIDATION_RESULT,
        name="static_validation",
        output={"passed": result.passed, "errors": result.errors},
        stage="compiler",
        sink=sink,
        bus=bus,
    )
    return result


def _split(text: str) -> tuple[dict[str, object] | None, str]:
    if not text.startswith("---\n"):
        return None, text
    parts = text.split("---\n", 2)
    if len(parts) < 3 or not parts[1].strip():
        return None, text
    loaded = yaml.safe_load(parts[1])
    if not isinstance(loaded, dict):
        return None, parts[2]
    return loaded, parts[2]


def _nvidia_frontmatter(raw: dict[str, object]) -> list[str]:
    """NVIDIA Agent Skills name and description limits. Extra SkillForge keys stay."""
    errors: list[str] = []
    name = raw.get("name")
    if isinstance(name, str) and (len(name) > 64 or _SKILL_NAME.match(name) is None):
        errors.append("frontmatter name must be a lowercase hyphenated skill name")
    description = raw.get("description")
    if isinstance(description, str) and len(description) > 1024:
        errors.append("frontmatter description exceeds 1024 characters")
    return errors


def _nvidia_layout(skill_dir: Path) -> list[str]:
    if not skill_dir.is_dir():
        return ["skill directory is missing"]
    errors: list[str] = []
    if not (skill_dir / "SKILL.md").is_file():
        errors.append("NVIDIA layout requires SKILL.md")
    for child in skill_dir.iterdir():
        if child.name not in _ALLOWED_PATHS:
            errors.append(f"unexpected skill path {child.name}")
    return errors


def _frontmatter(raw: dict[str, object]) -> list[str]:
    errors: list[str] = []
    name = raw.get("name")
    description = raw.get("description")
    if not isinstance(name, str) or not name.strip():
        errors.append("frontmatter requires name")
    if not isinstance(description, str) or not description.strip():
        errors.append("frontmatter requires description")
    if errors:
        return errors
    triggers = raw.get("triggers")
    tools = raw.get("tools")
    try:
        spec = SkillSpec(
            name=str(name).strip(),
            description=str(description).strip(),
            triggers=list(triggers) if isinstance(triggers, list) else [],
            tools=list(tools) if isinstance(tools, list) else [],
            permissions=raw.get("permissions") if isinstance(raw.get("permissions"), dict) else {},
        )
        validate_skill_spec(spec)
    except (SkillSpecError, ValidationError) as exc:
        errors.append(str(exc))
    return errors


def _coverage(body: str, source_map_path: Path) -> list[str]:
    instruction_ids = list(dict.fromkeys(_INS.findall(body)))
    if not instruction_ids:
        return ["SKILL.md has no instruction ids"]
    if not source_map_path.is_file():
        return ["source-map.json is missing"]
    loaded = json.loads(source_map_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return ["source-map.json must be an object"]
    missing = [item for item in instruction_ids if item not in loaded]
    if missing:
        return [f"source-map missing {', '.join(missing)}"]
    return []


def _procedure(body: str) -> str:
    start = body.find("## Procedure")
    if start < 0:
        return ""
    rest = body[start + len("## Procedure") :]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _banned(text: str) -> list[str]:
    errors: list[str] = []
    for pattern in _BANNED:
        if pattern.search(text):
            errors.append(f"banned command {pattern.pattern}")
    return errors


def _script(path: Path) -> list[str]:
    if not path.is_file():
        return [f"missing script {path.name}"]
    errors = _banned(path.read_text(encoding="utf-8"))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            py_compile.compile(str(path), cfile=str(Path(tmp) / "out.pyc"), doraise=True)
    except py_compile.PyCompileError as exc:
        errors.append(f"{path.name} failed to compile: {exc}")
    return errors
