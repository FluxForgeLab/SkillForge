"""Project persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from skillforge.domain.entities import Project


def insert_project(conn: sqlite3.Connection, project: Project) -> None:
    conn.execute(
        """
        INSERT INTO projects (id, name, description, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            project.id,
            project.name,
            project.description,
            project.created_at.isoformat(),
        ),
    )


def get_project(conn: sqlite3.Connection, project_id: str) -> Project | None:
    row = conn.execute(
        "SELECT id, name, description, created_at FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    _id, name, description, created_at = row
    return Project(
        id=_id,
        name=name,
        description=description,
        created_at=datetime.fromisoformat(created_at),
    )
