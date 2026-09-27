"""C6.6: golden skill passes static validation; broken copies fail."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from skillforge.compiler import validate_skill_dir
from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.tracing.bus import EventBus

_GOLDEN = Path(__file__).resolve().parents[3] / "skills" / "golden" / "service-recovery"


class _Sink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


async def test_golden_passes() -> None:
    sink = _Sink()
    result = await validate_skill_dir(
        _GOLDEN,
        run_id="validate_golden",
        sink=sink,
        bus=EventBus(),
    )
    assert result.passed, result.errors
    assert sink.events[-1].type is TraceEventType.VALIDATION_RESULT
    assert sink.events[-1].output["passed"] is True


async def test_missing_source_map_key_fails(tmp_path: Path) -> None:
    skill = _copy(tmp_path)
    path = skill / "references" / "source-map.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    del loaded["ins_01"]
    path.write_text(json.dumps(loaded), encoding="utf-8")
    result = await _validate(skill)
    assert result.passed is False
    assert any("ins_01" in error for error in result.errors)


async def test_sudo_in_procedure_fails(tmp_path: Path) -> None:
    skill = _copy(tmp_path)
    path = skill / "SKILL.md"
    text = path.read_text(encoding="utf-8").replace(
        "## Procedure\n",
        "## Procedure\n\nsudo reboot\n",
        1,
    )
    path.write_text(text, encoding="utf-8")
    result = await _validate(skill)
    assert result.passed is False
    assert any("sudo" in error for error in result.errors)


async def test_destructive_permissions_fail(tmp_path: Path) -> None:
    skill = _copy(tmp_path)
    path = skill / "SKILL.md"
    text = path.read_text(encoding="utf-8").replace(
        "destructive_commands: false",
        "destructive_commands: true",
        1,
    )
    path.write_text(text, encoding="utf-8")
    result = await _validate(skill)
    assert result.passed is False


async def test_broken_script_fails(tmp_path: Path) -> None:
    skill = _copy(tmp_path)
    (skill / "scripts" / "verify.py").write_text("def main(\n", encoding="utf-8")
    result = await _validate(skill)
    assert result.passed is False
    assert any("verify.py" in error for error in result.errors)


def _copy(tmp_path: Path) -> Path:
    dest = tmp_path / "skill"
    shutil.copytree(_GOLDEN, dest)
    return dest


async def _validate(skill: Path):
    return await validate_skill_dir(
        skill,
        run_id="validate_bad",
        sink=_Sink(),
        bus=EventBus(),
    )
