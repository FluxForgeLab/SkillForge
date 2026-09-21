"""Skill persistence."""

from __future__ import annotations

import sqlite3

from skillforge.domain.entities import Skill


def insert_skill(conn: sqlite3.Connection, skill: Skill) -> None:
    conn.execute(
        """
        INSERT INTO skills (id, project_id, name, description, current_version_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            skill.id,
            skill.project_id,
            skill.name,
            skill.description,
            skill.current_version_id,
        ),
    )


def get_skill(conn: sqlite3.Connection, skill_id: str) -> Skill | None:
    row = conn.execute(
        """
        SELECT id, project_id, name, description, current_version_id
        FROM skills WHERE id = ?
        """,
        (skill_id,),
    ).fetchone()
    if row is None:
        return None
    _id, project_id, name, description, current_version_id = row
    return Skill(
        id=_id,
        project_id=project_id,
        name=name,
        description=description,
        current_version_id=current_version_id,
    )


def update_skill_current_version(
    conn: sqlite3.Connection,
    skill_id: str,
    version_id: str,
) -> None:
    conn.execute(
        "UPDATE skills SET current_version_id = ? WHERE id = ?",
        (version_id, skill_id),
    )
