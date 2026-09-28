"""Generate a PatchProposal as a unified diff over SKILL.md / scripts."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from skillforge.config import Settings, get_settings
from skillforge.domain.entities import Failure, PatchProposal
from skillforge.evaluator.guard import evals_sha256, reject_patched_evals
from skillforge.evolution.diff_apply import (
    apply_unified_diff,
    iter_diff_paths,
    touches_evals,
)
from skillforge.evolution.errors import PatcherError
from skillforge.models.gateway import ModelGateway
from skillforge.models.structured import generate_structured
from skillforge.models.types import ChatMessage
from skillforge.runtime.tools.opslab import runtime_tools

_SYSTEM = (
    "You propose a minimal patch for an agent skill that failed evaluation. "
    "Return a unified diff that may change SKILL.md and/or files under scripts/ only. "
    "Never modify anything under evals/. "
    "Do not set shell.destructive_commands to true. "
    "Do not add tool names that are not already listed in the skill or "
    "in the allowed runtime tool set provided in the user message. "
    "Prefer adding missing instructions with clear source_ref citations when evidence exists."
)


class PatchDraft(BaseModel):
    """Model-proposed patch fields before deterministic validation."""

    model_config = ConfigDict(extra="forbid")

    diff: str
    summary: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class SkillPatcher:
    """Turn failure + evidence + skill tree into a validated PatchProposal."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._gateway = gateway
        self._settings = settings if settings is not None else get_settings()

    async def propose(
        self,
        *,
        skill_dir: Path,
        failure: Failure,
        benchmark: Mapping[str, Any] | BaseModel | None = None,
        target_skill_version_id: str | None = None,
        run_id: str | None = None,
    ) -> PatchProposal:
        skill_dir = Path(skill_dir)
        if not (skill_dir / "SKILL.md").is_file():
            raise PatcherError(f"SKILL.md missing under {skill_dir}")

        sealed = evals_sha256(skill_dir)
        known_tools = {item.name for item in runtime_tools().specs()}
        draft = await generate_structured(
            self._gateway,
            PatchDraft,
            run_id=run_id or failure.run_id,
            messages=[
                ChatMessage(role="system", content=_SYSTEM),
                ChatMessage(
                    role="user",
                    content=_user_prompt(
                        skill_dir,
                        failure,
                        benchmark,
                        known_tools=sorted(known_tools),
                    ),
                ),
            ],
            stage="evolution",
            settings=self._settings,
        )
        diff = draft.diff.strip()
        if not diff:
            raise PatcherError("empty patch diff")

        _reject_path_policy(diff)
        _validate_in_temp_copy(skill_dir, diff, sealed=sealed, known_tools=known_tools)

        refs = list(draft.evidence_refs) if draft.evidence_refs else list(failure.source_support)
        return PatchProposal(
            diff=diff if diff.endswith("\n") else diff + "\n",
            summary=draft.summary,
            target_skill_version_id=target_skill_version_id,
            evidence_refs=refs,
        )


def _user_prompt(
    skill_dir: Path,
    failure: Failure,
    benchmark: Mapping[str, Any] | BaseModel | None,
    *,
    known_tools: Sequence[str],
) -> str:
    files = _snapshot_patchable(skill_dir)
    bench: Any
    if benchmark is None:
        bench = None
    elif isinstance(benchmark, BaseModel):
        bench = benchmark.model_dump(mode="json")
    else:
        bench = dict(benchmark)
    payload = {
        "failure": failure.model_dump(by_alias=True, mode="json"),
        "benchmark": bench,
        "allowed_runtime_tools": list(known_tools),
        "skill_files": files,
    }
    return (
        "Propose a unified diff that fixes the skill gap. "
        "Touch only SKILL.md and/or scripts/*.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}"
    )


def _snapshot_patchable(skill_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        out["SKILL.md"] = skill_md.read_text(encoding="utf-8")
    scripts = skill_dir / "scripts"
    if scripts.is_dir():
        for path in sorted(scripts.rglob("*")):
            if path.is_file():
                rel = path.relative_to(skill_dir).as_posix()
                out[rel] = path.read_text(encoding="utf-8")
    return out


def _reject_path_policy(diff: str) -> None:
    """Allow SKILL.md, scripts/*, and evals/* (evals gated later by reject_patched_evals)."""
    for path in iter_diff_paths(diff):
        if path == "SKILL.md" or path.startswith("scripts/"):
            continue
        if path == "evals" or path.startswith("evals/"):
            continue
        raise PatcherError(f"patch path not allowed: {path!r}")


def _validate_in_temp_copy(
    skill_dir: Path,
    diff: str,
    *,
    sealed: str,
    known_tools: set[str],
) -> None:
    with tempfile.TemporaryDirectory(prefix="skillforge-patch-") as tmp:
        dest = Path(tmp) / "skill"
        shutil.copytree(skill_dir, dest)
        try:
            apply_unified_diff(dest, diff)
        except ValueError as exc:
            raise PatcherError(f"patch does not apply: {exc}") from exc
        # Hash contract from C4.5 — do not reimplement.
        reject_patched_evals(sealed, dest)
        if touches_evals(diff):
            raise PatcherError("patch must not touch evals/")
        _reject_permission_widening(dest, known_tools=known_tools)


def _reject_permission_widening(skill_dir: Path, *, known_tools: set[str]) -> None:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    meta, _body = _split_frontmatter(text)
    permissions = meta.get("permissions")
    if isinstance(permissions, Mapping):
        shell = permissions.get("shell")
        if isinstance(shell, Mapping) and bool(shell.get("destructive_commands")):
            raise PatcherError("patch must not set destructive_commands: true")

    tools = meta.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            name = str(tool)
            if name not in known_tools:
                raise PatcherError(f"patch adds unknown tool: {name!r}")


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    loaded = yaml.safe_load(parts[1])
    if not isinstance(loaded, dict):
        return {}, parts[2].lstrip("\n")
    return loaded, parts[2].lstrip("\n")
