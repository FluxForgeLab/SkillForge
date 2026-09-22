"""Evaluator load and guard errors."""

from __future__ import annotations

from skillforge.domain.errors import SkillForgeError


class EvalLoadError(SkillForgeError):
    """Raised when evals.json or its catalog mapping cannot be loaded."""


class EvalGuardError(SkillForgeError):
    """Raised when sealed evals.json is missing, duplicated, or tampered with."""
