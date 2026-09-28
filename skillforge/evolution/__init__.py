"""Failure analysis, patching, and evolution gates."""

from skillforge.evolution.analyzer import FailureAnalyzer
from skillforge.evolution.apply import apply_patch
from skillforge.evolution.evidence import enrich_source_support, query_text
from skillforge.evolution.patcher import SkillPatcher

__all__ = [
    "FailureAnalyzer",
    "SkillPatcher",
    "apply_patch",
    "enrich_source_support",
    "query_text",
]
