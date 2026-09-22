from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillforge.config import Settings
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelRequest, ModelResponse, TokenUsage
from skillforge.runtime.agent import LocalHarness
from skillforge.runtime.prompt import system_prompt
from skillforge.sandbox.base import ExecResult, Sandbox
from skillforge.tracing.bus import EventBus

_GOLDEN = Path(__file__).resolve().parents[2] / "skills" / "golden" / "service-recovery"
_SKILL = """---
name: demo
description: Demo skill.
triggers: [HTTP 502]
---

ins_01 Do the thing.
"""


class FakeSandbox(Sandbox):
    async def _create(self) -> None:
        return None

    async def _exec(self, command: str, *, timeout_sec: float) -> ExecResult:
        del command, timeout_sec
        return ExecResult(exit_code=0, stdout="", stderr="")

    async def _read_file(self, path: str) -> str:
        del path
        return ""

    async def _write_file(self, path: str, content: str) -> None:
        del path, content

    async def _destroy(self) -> None:
        return None


def _write_skill(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(_SKILL, encoding="utf-8")
    references = root / "references"
    references.mkdir()
    (references / "source-map.json").write_text(
        json.dumps(
            {
                "ins_01": {"document": "runbook.md", "page": 2},
                "ins_02": {},
            }
        ),
        encoding="utf-8",
    )


def test_bare_prompt_when_skill_path_is_none() -> None:
    prompt = system_prompt(None)
    assert prompt.startswith("You are the service recovery agent.")
    assert "# Skill" not in prompt


def test_skill_section_is_the_only_difference(tmp_path: Path) -> None:
    root = tmp_path / "demo-skill"
    _write_skill(root)
    bare = system_prompt(None)
    full = system_prompt(str(root))
    assert full.startswith(bare + "\n\n# Skill\n")
    suffix = full[len(bare) :]
    assert "name: demo" in suffix
    assert "description: Demo skill." in suffix
    assert "triggers: HTTP 502" in suffix
    assert "ins_01 Do the thing." in suffix
    assert "ins_01: document=runbook.md page=2" in suffix
    assert "ins_02" not in suffix
    assert "permissions" not in suffix


def test_golden_skill_omits_empty_references() -> None:
    prompt = system_prompt(str(_GOLDEN))
    bare = system_prompt(None)
    assert prompt.startswith(bare + "\n\n# Skill\n")
    assert "ins_01 docker.inspect" in prompt
    assert "# References" not in prompt
    assert "destructive_commands" not in prompt


def test_skill_file_path_uses_parent_directory(tmp_path: Path) -> None:
    root = tmp_path / "demo-skill"
    _write_skill(root)
    assert system_prompt(str(root / "SKILL.md")) == system_prompt(str(root))


def test_missing_skill_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SKILL.md not found"):
        system_prompt(str(tmp_path))
    skill = tmp_path / "SKILL.md"
    skill.write_text("secret skill", encoding="utf-8")
    with pytest.raises(ValueError, match="frontmatter"):
        system_prompt(str(skill))


async def test_both_arms_share_the_tool_list(tmp_path: Path) -> None:
    root = tmp_path / "demo-skill"
    _write_skill(root)
    settings = Settings(max_steps=2, max_seconds=30, temperature=0.0)
    done = ModelResponse(content="ok", finish_reason="stop", usage=TokenUsage(total_tokens=1))

    class Recording(FakeModelAdapter):
        def __init__(self) -> None:
            super().__init__([done])
            self.tools: set[str] = set()
            self.system = ""

        async def generate(self, request: ModelRequest) -> ModelResponse:
            self.tools = {tool.name for tool in request.tools}
            self.system = request.messages[0].content or ""
            return await super().generate(request)

    async def run(skill_path: str | None) -> Recording:
        adapter = Recording()
        gateway = ModelGateway(adapter, settings=settings, bus=EventBus())
        harness = LocalHarness(
            gateway=gateway,
            settings=settings,
            sandbox=FakeSandbox(),
            bus=EventBus(),
            run_id="run_c37",
        )
        await harness.run("restore", skill_path, str(tmp_path))
        return adapter

    bare = await run(None)
    full = await run(str(root))
    assert bare.tools == full.tools
    assert {"http.get", "docker.restart"} <= bare.tools
    assert full.system.startswith(bare.system + "\n\n# Skill\n")
