"""C7.4: apply PatchProposal → new DRAFT SkillVersion with parent + source-map."""

from __future__ import annotations

import difflib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from skillforge.config import Settings
from skillforge.db import initialize_database
from skillforge.db.connection import connection
from skillforge.db.repositories.projects import insert_project
from skillforge.domain.entities import PatchProposal, Project, SkillVersion, SkillVersionStatus
from skillforge.evolution.apply import apply_patch
from skillforge.evolution.errors import PatchApplyError
from skillforge.registry.service import SkillRegistry

_SKILL_MD_V01 = """\
---
name: service-recovery-mini
description: Mini skill for apply-patch tests.
version: 0.1.0
triggers: [HTTP 502]
tools: [docker.inspect, docker.restart, http.get]
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

_SOURCE_MAP_V01 = {
    "ins_01": {
        "knowledge_unit_id": "ku_down",
        "document": "runbook.md",
        "sha256": "abc123",
        "line_start": 1,
    },
    "ins_02": {
        "knowledge_unit_id": "ku_down",
        "document": "runbook.md",
        "sha256": "abc123",
        "line_start": 2,
    },
    "ins_03": {
        "knowledge_unit_id": "ku_down",
        "document": "runbook.md",
        "sha256": "abc123",
        "line_start": 3,
    },
}


def _unified(old: str, new: str, *, path: str = "SKILL.md") -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )


def _with_instruction(line: str) -> str:
    return _SKILL_MD_V01.replace(
        "ins_03 http.get http://127.0.0.1:8088/health.\n",
        "ins_03 http.get http://127.0.0.1:8088/health.\n" + line + "\n",
    )


def _registry(tmp_path: Path) -> tuple[SkillRegistry, str]:
    db_path = tmp_path / "apply.db"
    initialize_database(db_path)
    project_id = f"proj_{uuid4().hex}"
    with connection(db_path) as conn:
        insert_project(
            conn,
            Project(
                id=project_id,
                name="Apply Patch Project",
                description=None,
                created_at=datetime.now(UTC),
            ),
        )
    settings = Settings(_env_file=None)
    registry = SkillRegistry(
        db_path,
        generated_root=tmp_path / "generated",
        path_prefix=settings.skills_generated_dir.as_posix(),
        settings=settings,
    )
    return registry, project_id


def _seed_v01(tmp_path: Path) -> tuple[SkillRegistry, SkillVersion, Path]:
    registry, project_id = _registry(tmp_path)
    skill = registry.create_skill(project_id, "service-recovery-mini")
    files = {
        "SKILL.md": _SKILL_MD_V01.encode("utf-8"),
        "evals/evals.json": _EVALS.encode("utf-8"),
        "scripts/diagnose.py": b'print("diagnose")\n',
        "references/source-map.json": (
            json.dumps(_SOURCE_MAP_V01, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8"),
    }
    version = registry.create_version(skill.id, "0.1", files)
    parent_dir = tmp_path / "generated" / "service-recovery-mini" / "0.1"
    return registry, version, parent_dir


def test_apply_adds_ins_08_with_source_map(tmp_path: Path) -> None:
    registry, parent, parent_dir = _seed_v01(tmp_path)
    new_md = _with_instruction("ins_08 Run nginx -t before reload.")
    proposal = PatchProposal(
        diff=_unified(_SKILL_MD_V01, new_md),
        summary="Add nginx -t instruction",
        target_skill_version_id=parent.id,
        evidence_refs=["doc#appendix-b"],
    )
    updates = {
        "ins_08": {
            "knowledge_unit_id": "ku_appendix",
            "document": "runbook.md",
            "sha256": "abc123",
            "page": 12,
        },
    }

    created = apply_patch(
        registry,
        parent_version_id=parent.id,
        parent_dir=parent_dir,
        proposal=proposal,
        source_map_updates=updates,
        version="0.2",
    )

    assert created.parent_version_id == parent.id
    assert created.status == SkillVersionStatus.DRAFT
    assert created.version == "0.2"

    new_dir = tmp_path / "generated" / "service-recovery-mini" / "0.2"
    skill_md = (new_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "ins_08 Run nginx -t before reload." in skill_md
    source_map = json.loads(
        (new_dir / "references" / "source-map.json").read_text(encoding="utf-8")
    )
    assert source_map["ins_08"]["knowledge_unit_id"] == "ku_appendix"
    assert source_map["ins_08"]["page"] == 12
    assert source_map["ins_01"]["knowledge_unit_id"] == "ku_down"
    assert (new_dir / "evals" / "evals.json").is_file()


def test_apply_rejects_empty_source_map_for_new_ins(tmp_path: Path) -> None:
    registry, parent, parent_dir = _seed_v01(tmp_path)
    new_md = _with_instruction("ins_09 Touch config without source_ref.")
    proposal = PatchProposal(
        diff=_unified(_SKILL_MD_V01, new_md),
        summary="Bad patch without provenance",
        target_skill_version_id=parent.id,
    )

    with pytest.raises(PatchApplyError, match="empty source-map"):
        apply_patch(
            registry,
            parent_version_id=parent.id,
            parent_dir=parent_dir,
            proposal=proposal,
            source_map_updates={"ins_09": {}},
            version="0.2",
        )

    versions = registry.list_versions(parent.skill_id)
    assert [item.version for item in versions] == ["0.1"]
