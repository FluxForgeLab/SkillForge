"""SkillVersion persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from skillforge.domain.entities import SkillVersion
from skillforge.domain.state_machines import SkillVersionStatus


def _row_to_version(row: tuple[object, ...]) -> SkillVersion:
    (
        _id,
        skill_id,
        version,
        parent_version_id,
        status,
        artifact_path,
        manifest_hash,
        created_at,
    ) = row
    return SkillVersion(
        id=str(_id),
        skill_id=str(skill_id),
        version=str(version),
        parent_version_id=str(parent_version_id) if parent_version_id else None,
        status=SkillVersionStatus(str(status)),
        artifact_path=str(artifact_path) if artifact_path else None,
        manifest_hash=str(manifest_hash) if manifest_hash else None,
        created_at=datetime.fromisoformat(str(created_at)),
    )


def insert_skill_version(conn: sqlite3.Connection, skill_version: SkillVersion) -> None:
    conn.execute(
        """
        INSERT INTO skill_versions (
            id, skill_id, version, parent_version_id, status,
            artifact_path, manifest_hash, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            skill_version.id,
            skill_version.skill_id,
            skill_version.version,
            skill_version.parent_version_id,
            skill_version.status.value,
            skill_version.artifact_path,
            skill_version.manifest_hash,
            skill_version.created_at.isoformat(),
        ),
    )


def get_skill_version(conn: sqlite3.Connection, version_id: str) -> SkillVersion | None:
    row = conn.execute(
        """
        SELECT id, skill_id, version, parent_version_id, status,
               artifact_path, manifest_hash, created_at
        FROM skill_versions WHERE id = ?
        """,
        (version_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_version(row)


def list_skill_versions(conn: sqlite3.Connection, skill_id: str) -> list[SkillVersion]:
    rows = conn.execute(
        """
        SELECT id, skill_id, version, parent_version_id, status,
               artifact_path, manifest_hash, created_at
        FROM skill_versions
        WHERE skill_id = ?
        ORDER BY created_at ASC
        """,
        (skill_id,),
    ).fetchall()
    return [_row_to_version(row) for row in rows]


def find_skill_version_by_label(
    conn: sqlite3.Connection,
    skill_id: str,
    version: str,
) -> SkillVersion | None:
    row = conn.execute(
        """
        SELECT id, skill_id, version, parent_version_id, status,
               artifact_path, manifest_hash, created_at
        FROM skill_versions
        WHERE skill_id = ? AND version = ?
        """,
        (skill_id, version),
    ).fetchone()
    if row is None:
        return None
    return _row_to_version(row)


def update_skill_version_status(
    conn: sqlite3.Connection,
    version_id: str,
    status: SkillVersionStatus,
) -> None:
    conn.execute(
        "UPDATE skill_versions SET status = ? WHERE id = ?",
        (status.value, version_id),
    )
