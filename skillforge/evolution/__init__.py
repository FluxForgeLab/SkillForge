"""Failure analysis, patching, and evolution gates."""

from skillforge.evolution.analyzer import FailureAnalyzer
from skillforge.evolution.apply import apply_patch
from skillforge.evolution.evidence import enrich_source_support, query_text
from skillforge.evolution.gate import (
    EvolutionGateReport,
    GateCondition,
    evaluate_evolution_gate,
    run_regression,
)
from skillforge.evolution.patcher import SkillPatcher

__all__ = [
    "EvolutionGateReport",
    "FailureAnalyzer",
    "GateCondition",
    "SkillPatcher",
    "apply_patch",
    "enrich_source_support",
    "evaluate_evolution_gate",
    "query_text",
    "run_regression",
]
