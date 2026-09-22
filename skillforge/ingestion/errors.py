"""Ingestion errors."""

from __future__ import annotations

from skillforge.domain.errors import SkillForgeError


class IngestError(SkillForgeError):
    """Raised when an upload cannot be stored or parsed."""
