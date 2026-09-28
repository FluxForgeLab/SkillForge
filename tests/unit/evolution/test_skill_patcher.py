"""C7.3: SkillPatcher emits PatchProposal unified diffs; evals/ and permission widening rejected."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

import pytest

from skillforge.config import Settings
from skillforge.domain.entities import Failure
from skillforge.evaluator.errors import EvalGuardError
from skillforge.evolution.diff_apply import apply_unified_diff
from skillforge.evolution.errors import PatcherError
from skillforge.evolution.patcher import SkillPatcher
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.tracing.bus import EventBus

_SKILL_MD = """\
---
name: service-recovery-mini
description: Mini skill for patcher tests.
version: 0.1.0
triggers: [HTTP 502]
tools: [docker.inspect, docker.restart, nginx.reload, http.get]
permissions:
  filesystem: {read: [/workspace], write: [/workspace/runtime]}
  network: {allow: [localhost]}
  shell: {destructive_commands: false}
---

# Service Recovery Mini

## Procedure

ins_01 docker.inspect backend.
ins_02 If stopped, docker.restart backend.
ins_03 http.get http://127.0.0.1:8088/health.
"""

_EVALS = """\
[
  {
    "id": "eval_backend_stopped",
    "name": "backend process stopped",
    "task": "Restore it.",
    "fixture": "backend_stopped",
    "expected": {"http_status": 200},
    "forbidden": ["delete_volume"],
    "timeout_sec": 180
  }
]
"""

_SCRIPT = 'print("diagnose")\n'


def _write_skill(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    (root / "evals").mkdir()
    (root / "evals" / "evals.json").write_text(_EVALS, encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "diagnose.py").write_text(_SCRIPT, encoding="utf-8")
    return root


def _failure() -> Failure:
    return Failure.model_validate(
        {
            "run_id": "run_patch_001",
            "class": "missing_instruction",
            "symptom": "nginx reload failed without nginx -t",
            "failed_assertion": "nginx_config_valid",
            "evidence": ["nginx reload failed"],
            "suspected_skill_gap": "missing nginx -t before reload",
            "source_support": ["doc#appendix-b"],
        }
    )


def _unified(old: str, new: str, *, path: str = "SKILL.md") -> str:
    diff = "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )
    if not old.endswith("\n"):
        # difflib may omit trailing newline markers; keep content applyable
        pass
    return diff


def _gateway(draft: dict) -> ModelGateway:
    return ModelGateway(
        FakeModelAdapter([ModelResponse(content=json.dumps(draft))]),
        settings=Settings(_env_file=None),
        bus=EventBus(),
    )


def _skill_with_instruction(extra_line: str) -> str:
    return _SKILL_MD.replace(
        "ins_03 http.get http://127.0.0.1:8088/health.\n",
        f"ins_03 {extra_line}\nins_04 http.get http://127.0.0.1:8088/health.\n",
    )


@pytest.mark.asyncio
async def test_good_diff_applies_and_returns_proposal(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path / "skill")
    new_md = _skill_with_instruction(
        "Run nginx.test before nginx.reload when config may be invalid."
    )
    diff = _unified(_SKILL_MD, new_md)
    assert diff
    draft = {
        "diff": diff,
        "summary": "Add nginx -t before reload",
        "evidence_refs": ["doc#appendix-b"],
    }
    patcher = SkillPatcher(_gateway(draft), settings=Settings(_env_file=None))
    proposal = await patcher.propose(
        skill_dir=skill_dir,
        failure=_failure(),
        benchmark={"uplift_pp": -50.0},
        target_skill_version_id="sv_prev",
    )
    assert proposal.summary == "Add nginx -t before reload"
    assert proposal.target_skill_version_id == "sv_prev"
    assert proposal.evidence_refs == ["doc#appendix-b"]
    assert "nginx.test" in proposal.diff

    apply_dir = tmp_path / "applied"
    apply_dir.mkdir()
    (apply_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    apply_unified_diff(apply_dir, proposal.diff)
    assert "nginx.test" in (apply_dir / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_evals_diff_rejected_via_guard(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path / "skill")
    tampered = '[{"id":"hacked","expected":{"http_status":200}}]\n'
    diff = _unified(_EVALS, tampered, path="evals/evals.json")
    draft = {"diff": diff, "summary": "weaken evals", "evidence_refs": []}
    patcher = SkillPatcher(_gateway(draft), settings=Settings(_env_file=None))
    with pytest.raises(EvalGuardError):
        await patcher.propose(skill_dir=skill_dir, failure=_failure())


@pytest.mark.asyncio
async def test_destructive_commands_diff_rejected(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path / "skill")
    widened = _SKILL_MD.replace(
        "shell: {destructive_commands: false}",
        "shell: {destructive_commands: true}",
    )
    diff = _unified(_SKILL_MD, widened)
    draft = {"diff": diff, "summary": "widen", "evidence_refs": []}
    patcher = SkillPatcher(_gateway(draft), settings=Settings(_env_file=None))
    with pytest.raises(PatcherError, match="destructive_commands"):
        await patcher.propose(skill_dir=skill_dir, failure=_failure())


@pytest.mark.asyncio
async def test_unknown_tool_diff_rejected(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path / "skill")
    widened = _SKILL_MD.replace(
        "tools: [docker.inspect, docker.restart, nginx.reload, http.get]",
        "tools: [docker.inspect, docker.restart, nginx.reload, http.get, shell.exec]",
    )
    diff = _unified(_SKILL_MD, widened)
    draft = {"diff": diff, "summary": "add tool", "evidence_refs": []}
    patcher = SkillPatcher(_gateway(draft), settings=Settings(_env_file=None))
    with pytest.raises(PatcherError, match="unknown tool"):
        await patcher.propose(skill_dir=skill_dir, failure=_failure())
