"""Persisted evaluator results. Separate from agent_runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from skillforge.domain.entities import EvaluationRun
from skillforge.domain.enums import EvaluationRunStatus


def insert_evaluation_run(conn: sqlite3.Connection, run: EvaluationRun) -> None:
    conn.execute(
        """
        INSERT INTO evaluation_runs (
            id, skill_version_id, baseline, metrics, status, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.id,
            run.skill_version_id,
            json.dumps(run.baseline),
            json.dumps(run.metrics),
            run.status.value,
            run.started_at.isoformat(),
            run.finished_at.isoformat() if run.finished_at is not None else None,
        ),
    )


def _row_to_evaluation_run(row: tuple[object, ...]) -> EvaluationRun:
    finished = row[6]
    return EvaluationRun(
        id=row[0],
        skill_version_id=row[1],
        baseline=json.loads(row[2]),
        metrics=json.loads(row[3]),
        status=EvaluationRunStatus(row[4]),
        started_at=datetime.fromisoformat(row[5]),
        finished_at=datetime.fromisoformat(finished) if finished is not None else None,
    )


def get_evaluation_run(conn: sqlite3.Connection, run_id: str) -> EvaluationRun | None:
    row = conn.execute(
        """
        SELECT id, skill_version_id, baseline, metrics, status, started_at, finished_at
        FROM evaluation_runs
        WHERE id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_evaluation_run(row)


def list_evaluation_runs_for_skill(
    conn: sqlite3.Connection,
    skill_id: str,
) -> list[EvaluationRun]:
    """Return evaluation runs whose skill_version belongs to ``skill_id``."""
    rows = conn.execute(
        """
        SELECT er.id, er.skill_version_id, er.baseline, er.metrics,
               er.status, er.started_at, er.finished_at
        FROM evaluation_runs AS er
        INNER JOIN skill_versions AS sv ON sv.id = er.skill_version_id
        WHERE sv.skill_id = ?
        ORDER BY er.started_at DESC, er.id DESC
        """,
        (skill_id,),
    ).fetchall()
    return [_row_to_evaluation_run(row) for row in rows]
