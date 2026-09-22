"""Read-only evals seals for candidate skill versions."""

from __future__ import annotations

import sqlite3


def insert_eval_seal(conn: sqlite3.Connection, skill_version_id: str, evals_sha256: str) -> None:
    conn.execute(
        """
        INSERT INTO eval_seals (skill_version_id, evals_sha256)
        VALUES (?, ?)
        """,
        (skill_version_id, evals_sha256),
    )


def get_eval_seal(conn: sqlite3.Connection, skill_version_id: str) -> str | None:
    row = conn.execute(
        "SELECT evals_sha256 FROM eval_seals WHERE skill_version_id = ?",
        (skill_version_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])
