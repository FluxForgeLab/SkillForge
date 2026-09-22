"""Seal and verify evals.json so candidates cannot rewrite fixtures or expected."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.eval_seals import get_eval_seal, insert_eval_seal
from skillforge.evaluator.errors import EvalGuardError


def evals_sha256(skill_dir: Path) -> str:
    """Hash raw bytes of ``skill_dir/evals/evals.json``."""
    path = Path(skill_dir) / "evals" / "evals.json"
    if not path.is_file():
        raise EvalGuardError(f"evals.json missing under {skill_dir}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_candidate_evals(db_path: Path, skill_version_id: str, skill_dir: Path) -> str:
    """Compute evals sha and insert a seal. Existing seals are never replaced."""
    digest = evals_sha256(skill_dir)
    initialize_database(db_path)
    try:
        with connection(db_path) as conn:
            insert_eval_seal(conn, skill_version_id, digest)
    except sqlite3.IntegrityError as exc:
        raise EvalGuardError(
            f"eval seal already exists for skill_version_id={skill_version_id!r}"
        ) from exc
    return digest


def verify_sealed_evals(db_path: Path, skill_version_id: str, skill_dir: Path) -> None:
    """If a seal exists, require the current evals.json hash to match."""
    initialize_database(db_path)
    with connection(db_path) as conn:
        sealed = get_eval_seal(conn, skill_version_id)
    if sealed is None:
        return
    current = evals_sha256(skill_dir)
    if current != sealed:
        raise EvalGuardError(
            f"evals.json hash mismatch for skill_version_id={skill_version_id!r}: "
            f"sealed={sealed} current={current}"
        )


def reject_patched_evals(sealed_sha256: str, patched_dir: Path) -> None:
    """Patcher gate: reject if patched skill directory altered evals.json."""
    current = evals_sha256(patched_dir)
    if current != sealed_sha256:
        raise EvalGuardError(
            f"patched evals.json hash mismatch: sealed={sealed_sha256} current={current}"
        )
