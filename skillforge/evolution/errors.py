"""Evolution-stage errors (analysis, patching, gates)."""

from __future__ import annotations

from skillforge.domain.errors import SkillForgeError


class PatcherError(SkillForgeError):
    """Raised when a model patch proposal is invalid, unsafe, or cannot be applied."""


class PatchApplyError(SkillForgeError):
    """Raised when applying a PatchProposal to create a new SkillVersion fails."""
