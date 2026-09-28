"""NVIDIA SkillEvaluator adapter. The demo path uses the deterministic evaluator.

The CLI wrapper runs an external binary only when one is configured and present.
Otherwise the mock reports three tiers without pretending a live NVIDIA run happened.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

TierName = Literal["tier1_validation", "tier2_deduplication", "tier3_live"]
EvalSource = Literal["mock", "cli"]


class TierResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: TierName
    passed: bool | None
    detail: str
    source: EvalSource


def evaluate_skill(skill_dir: Path, *, command: str | None = None) -> list[TierResult]:
    """Return Tier 1/2/3. A missing external command falls back to the mock."""
    if command:
        binary = command.split()[0]
        if shutil.which(binary) is not None:
            return _from_cli(skill_dir, command)
    return mock_skill_evaluation(skill_dir)


def mock_skill_evaluation(skill_dir: Path) -> list[TierResult]:
    """Deterministic stand-in. Tier 3 is not run."""
    skill_md = skill_dir / "SKILL.md"
    tier1_passed = False
    tier1_detail = "SKILL.md is missing"
    name = ""
    if skill_md.is_file():
        text = skill_md.read_text(encoding="utf-8")
        meta = _frontmatter(text)
        name = str(meta.get("name") or "")
        description = str(meta.get("description") or "")
        tier1_passed = bool(name.strip() and description.strip())
        tier1_detail = (
            "frontmatter has name and description" if tier1_passed else "frontmatter incomplete"
        )
    return [
        TierResult(
            tier="tier1_validation",
            passed=tier1_passed,
            detail=tier1_detail,
            source="mock",
        ),
        TierResult(
            tier="tier2_deduplication",
            passed=True,
            detail=f"single directory {name or skill_dir.name}; no catalog comparison",
            source="mock",
        ),
        TierResult(
            tier="tier3_live",
            passed=None,
            detail="live tier is not run by the mock",
            source="mock",
        ),
    ]


def _from_cli(skill_dir: Path, command: str) -> list[TierResult]:
    completed = subprocess.run(
        [*command.split(), str(skill_dir)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        return [
            TierResult(
                tier=tier,
                passed=False,
                detail=completed.stderr.strip()[:200] or f"exit {completed.returncode}",
                source="cli",
            )
            for tier in ("tier1_validation", "tier2_deduplication", "tier3_live")
        ]
    loaded = json.loads(completed.stdout)
    if not isinstance(loaded, list):
        raise ValueError("skill evaluator stdout must be a JSON list")
    return [TierResult.model_validate(item) for item in loaded]


def _frontmatter(text: str) -> dict[str, object]:
    if not text.startswith("---\n"):
        return {}
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}
    loaded = yaml.safe_load(parts[1])
    return loaded if isinstance(loaded, dict) else {}
