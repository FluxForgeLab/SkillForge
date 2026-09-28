"""Apply a PatchProposal onto a prior skill tree and register a new DRAFT version."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from skillforge.domain.entities import PatchProposal, SkillVersion
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.evolution.diff_apply import apply_unified_diff
from skillforge.evolution.errors import PatchApplyError
from skillforge.registry.service import SkillRegistry

_INS = re.compile(r"ins_\d+")
_SOURCE_MAP_REL = "references/source-map.json"
_MEANINGFUL_KEYS = ("knowledge_unit_id", "document", "sha256")
_COORD_KEYS = ("page", "line_start", "line_end")


def apply_patch(
    registry: SkillRegistry,
    *,
    parent_version_id: str,
    parent_dir: Path,
    proposal: PatchProposal,
    source_map_updates: Mapping[str, Mapping[str, Any]],
    version: str,
) -> SkillVersion:
    """Copy ``parent_dir``, apply the unified diff, merge source-map, create DRAFT version.

    Does not call approve/publish or ``record_candidate_evals``. New ``ins_xx`` ids
    introduced by the patch must receive a non-empty source-map entry via
    ``source_map_updates`` (compiler shape: knowledge_unit_id / document / sha256 /
    optional page or line coords).
    """
    parent_dir = Path(parent_dir)
    if not (parent_dir / "SKILL.md").is_file():
        raise PatchApplyError(f"SKILL.md missing under {parent_dir}")

    parent = registry.get_version(parent_version_id)
    before_ids = _instruction_ids((parent_dir / "SKILL.md").read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="skillforge-apply-") as tmp:
        dest = Path(tmp) / "skill"
        shutil.copytree(parent_dir, dest)
        manifest = dest / "manifest.json"
        if manifest.is_file():
            manifest.unlink()

        try:
            apply_unified_diff(dest, proposal.diff)
        except ValueError as exc:
            raise PatchApplyError(f"patch does not apply: {exc}") from exc

        after_ids = _instruction_ids((dest / "SKILL.md").read_text(encoding="utf-8"))
        new_ids = [item for item in after_ids if item not in before_ids]

        merged = _load_source_map(dest)
        for instruction_id, entry in source_map_updates.items():
            merged[instruction_id] = dict(entry)

        _reject_missing_source_refs(new_ids, merged)
        _write_source_map(dest, merged)

        files = _collect_files(dest)

    return registry.create_version(
        parent.skill_id,
        version,
        files,
        parent_version_id=parent_version_id,
        initial_status=SkillVersionStatus.DRAFT,
    )


def _instruction_ids(skill_md: str) -> list[str]:
    return list(dict.fromkeys(_INS.findall(skill_md)))


def _load_source_map(skill_dir: Path) -> dict[str, dict[str, Any]]:
    path = skill_dir / _SOURCE_MAP_REL
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise PatchApplyError("source-map.json must be an object")
    out: dict[str, dict[str, Any]] = {}
    for key, value in loaded.items():
        if isinstance(value, dict):
            out[str(key)] = dict(value)
        else:
            raise PatchApplyError(f"source-map entry {key!r} must be an object")
    return out


def _write_source_map(skill_dir: Path, source_map: Mapping[str, Mapping[str, Any]]) -> None:
    path = skill_dir / _SOURCE_MAP_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(source_map), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _reject_missing_source_refs(
    new_ids: list[str],
    source_map: Mapping[str, Mapping[str, Any]],
) -> None:
    missing: list[str] = []
    empty: list[str] = []
    for instruction_id in new_ids:
        if instruction_id not in source_map:
            missing.append(instruction_id)
            continue
        if not _entry_is_nonempty(source_map[instruction_id]):
            empty.append(instruction_id)
    if missing:
        raise PatchApplyError(
            f"new instructions lack source-map entries: {', '.join(missing)}",
        )
    if empty:
        raise PatchApplyError(
            f"new instructions have empty source-map entries: {', '.join(empty)}",
        )


def _entry_is_nonempty(entry: Mapping[str, Any]) -> bool:
    """Non-empty means compiler-shaped provenance, not ``{}``."""
    for key in _MEANINGFUL_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return True
    for key in _COORD_KEYS:
        if entry.get(key) is not None:
            return True
    return False


def _collect_files(skill_dir: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(skill_dir).as_posix()
        if rel == "manifest.json":
            continue
        files[rel] = path.read_bytes()
    return files
