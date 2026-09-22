"""Evaluator load and guard errors."""

from __future__ import annotations

from skillforge.domain.errors import SkillForgeError


class EvalLoadError(SkillForgeError):
    """Raised when evals.json or its catalog mapping cannot be loaded."""


class EvalGuardError(SkillForgeError):
    """Raised when sealed evals.json is missing, duplicated, or tampered with."""


class CacheMiss(SkillForgeError):
    """Raised when a cached eval trial is required but missing."""

    def __init__(self, case_id: str, arm: str) -> None:
        self.case_id = case_id
        self.arm = arm
        super().__init__(f"eval cache miss: case_id={case_id!r} arm={arm!r}")
