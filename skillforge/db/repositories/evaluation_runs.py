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
