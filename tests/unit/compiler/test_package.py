"""C6.7: a validated skill is stored as CANDIDATE and does not seal evals."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from skillforge.compiler import package_skill
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.eval_seals import get_eval_seal
from skillforge.db.repositories.projects import insert_project
from skillforge.domain.entities import Project
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.registry.service import SkillRegistry
from skillforge.tracing.bus import EventBus

_GOLDEN = Path(__file__).resolve().parents[3] / "skills" / "golden" / "service-recovery"


class _Sink:
    async def write(self, event: object) -> None:
        del event


async def test_golden_package_becomes_candidate_without_seal(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    version = await package_skill(
        _GOLDEN,
        "proj_pkg",
        registry,
        run_id="pkg_ok",
        sink=_Sink(),
        bus=EventBus(),
    )
    assert version.status is SkillVersionStatus.CANDIDATE
    card = tmp_path / "generated" / "service-recovery" / "0.1.0" / "skill-card.md"
    text = card.read_text(encoding="utf-8")
    assert "ins_01" in text
    assert "eval_backend_stopped" in text
    with connection(tmp_path / "app.sqlite") as conn:
        assert get_eval_seal(conn, version.id) is None


async def test_failed_validation_stays_draft(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    shutil.copytree(_GOLDEN, skill)
    source_map = skill / "references" / "source-map.json"
    loaded = json.loads(source_map.read_text(encoding="utf-8"))
    del loaded["ins_01"]
    source_map.write_text(json.dumps(loaded), encoding="utf-8")
    version = await package_skill(
        skill,
        "proj_pkg",
        _registry(tmp_path),
        run_id="pkg_bad",
        sink=_Sink(),
        bus=EventBus(),
    )
    assert version.status is SkillVersionStatus.DRAFT


def _registry(tmp_path: Path) -> SkillRegistry:
    db_path = tmp_path / "app.sqlite"
    initialize_database(db_path)
    with connection(db_path) as conn:
        insert_project(
            conn,
            Project(id="proj_pkg", name="lab", created_at=datetime(2026, 1, 1, tzinfo=UTC)),
        )
    return SkillRegistry(db_path, generated_root=tmp_path / "generated")
