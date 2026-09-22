"""Evaluator load errors."""

from __future__ import annotations

from skillforge.domain.errors import SkillForgeError


class EvalLoadError(SkillForgeError):
    """Raised when evals.json or its catalog mapping cannot be loaded."""
