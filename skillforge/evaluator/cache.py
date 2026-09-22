"""Persist and replay evaluation trial results by (version_hash, case, arm, model)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.domain.entities import EvaluationRun
from skillforge.domain.enums import EvaluationRunStatus
from skillforge.evaluator.errors import CacheMiss

_REPLAY_AT = datetime(2026, 1, 1, tzinfo=UTC)


def store_trial(
    db_path: Path,
    *,
    version_hash: str,
    case_id: str,
    arm: str,
    model: str,
    baseline: bool,
    metrics: dict[str, Any],
    status: str,
) -> None:
    """INSERT OR REPLACE one cached trial so a fresh live run updates the cache."""
    initialize_database(db_path)
    payload = json.dumps({"baseline": baseline, "metrics": metrics, "status": status})
    with connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO eval_cache (
                version_hash, case_id, arm, model, payload
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (version_hash, case_id, arm, model, payload),
        )


def load_trial(
    db_path: Path,
    *,
    version_hash: str,
    case_id: str,
    arm: str,
    model: str,
) -> dict[str, Any] | None:
    """Return cached payload dict, or None when the row is missing."""
    initialize_database(db_path)
    with connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT payload FROM eval_cache
            WHERE version_hash = ? AND case_id = ? AND arm = ? AND model = ?
            """,
            (version_hash, case_id, arm, model),
        ).fetchone()
    if row is None:
        return None
    payload = json.loads(row[0])
    if not isinstance(payload, dict):
        return None
    return payload


def replay_trials(
    db_path: Path,
    *,
    version_hash: str,
    model: str,
    case_ids: list[str],
) -> list[EvaluationRun]:
    """Build deterministic EvaluationRun rows from cache; raise CacheMiss if incomplete."""
    runs: list[EvaluationRun] = []
    for case_id in case_ids:
        for arm in ("control", "treatment"):
            payload = load_trial(
                db_path,
                version_hash=version_hash,
                case_id=case_id,
                arm=arm,
                model=model,
            )
            if payload is None:
                raise CacheMiss(case_id, arm)
            runs.append(
                EvaluationRun(
                    id=f"replay_{version_hash}_{case_id}_{arm}",
                    skill_version_id="replay",
                    baseline={"baseline": payload["baseline"]},
                    metrics=dict(payload["metrics"]),
                    status=EvaluationRunStatus(payload["status"]),
                    started_at=_REPLAY_AT,
                    finished_at=_REPLAY_AT,
                )
            )
    return runs
