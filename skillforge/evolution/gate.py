"""Regression suite runner and §8.14 Evolution Gate (five deterministic conditions)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from skillforge.domain.entities import EvaluationRun, Failure
from skillforge.evaluator.cases import LoadedEvalCase
from skillforge.evaluator.suite import HarnessFactory, SuiteReport, run_suite

SuiteRunner = Callable[..., Awaitable[SuiteReport]]


class GateCondition(StrEnum):
    """Named §8.14 Evolution Gate checks."""

    SUCCESS_RATE_NON_DECREASING = "success_rate_non_decreasing"
    TARGET_FAILURE_FIXED = "target_failure_fixed"
    NO_CRITICAL_REGRESSION = "no_critical_regression"
    NO_NEW_SECURITY_VIOLATION = "no_new_security_violation"
    SOURCE_EVIDENCE_EXISTS = "source_evidence_exists"


class EvolutionGateReport(BaseModel):
    """Gate outcome: overall pass plus which conditions failed."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    failed_conditions: list[GateCondition] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)


async def run_regression(
    cases: Sequence[LoadedEvalCase],
    *,
    skill_path: str,
    skill_version_id: str,
    workspace: str,
    harness_factory: HarnessFactory,
    db_path: Path,
    repeats: int = 1,
    suite_runner: SuiteRunner | None = None,
    **passthrough: Any,
) -> SuiteReport:
    """Run the full eval suite for a candidate skill.

    Defaults to ``run_suite``. Unit tests inject ``suite_runner`` so no Docker / ops-lab
    is required. Does not approve or publish.
    """
    runner = suite_runner if suite_runner is not None else run_suite
    return await runner(
        cases,
        skill_path=skill_path,
        skill_version_id=skill_version_id,
        workspace=workspace,
        harness_factory=harness_factory,
        db_path=db_path,
        repeats=repeats,
        **passthrough,
    )


def evaluate_evolution_gate(
    *,
    previous: SuiteReport,
    candidate: SuiteReport,
    failure: Failure,
) -> EvolutionGateReport:
    """Check all five §8.14 conditions against previous vs candidate suite reports.

    Reuses ``SuiteReport`` / ``ArmSummary`` success rates and ``policy_violations``.
    Does not recompute uplift; ``uplift_pp`` is left untouched on the reports.
    """
    checks: dict[str, bool] = {}
    failed: list[GateCondition] = []

    def _record(condition: GateCondition, ok: bool) -> None:
        checks[condition.value] = ok
        if not ok:
            failed.append(condition)

    _record(
        GateCondition.SUCCESS_RATE_NON_DECREASING,
        candidate.treatment.success_rate >= previous.treatment.success_rate,
    )
    _record(
        GateCondition.TARGET_FAILURE_FIXED,
        _target_failure_fixed(previous=previous, candidate=candidate, failure=failure),
    )
    _record(
        GateCondition.NO_CRITICAL_REGRESSION,
        _no_critical_regression(previous=previous, candidate=candidate),
    )
    _record(
        GateCondition.NO_NEW_SECURITY_VIOLATION,
        _no_new_security_violation(previous=previous, candidate=candidate),
    )
    _record(
        GateCondition.SOURCE_EVIDENCE_EXISTS,
        bool(failure.source_support),
    )

    return EvolutionGateReport(
        passed=not failed,
        failed_conditions=failed,
        checks=checks,
    )


def _target_failure_fixed(
    *,
    previous: SuiteReport,
    candidate: SuiteReport,
    failure: Failure,
) -> bool:
    case_id = _case_id_for_failure(previous, failure)
    if case_id is None:
        return False
    rates = _treatment_success_by_case(candidate.runs)
    return rates.get(case_id, 0.0) >= 1.0


def _no_critical_regression(*, previous: SuiteReport, candidate: SuiteReport) -> bool:
    """A previously fully-passing treatment case must not drop in success rate."""
    prev_rates = _treatment_success_by_case(previous.runs)
    cand_rates = _treatment_success_by_case(candidate.runs)
    for case_id, prev_rate in prev_rates.items():
        if prev_rate < 1.0:
            continue
        if cand_rates.get(case_id, 0.0) < prev_rate:
            return False
    return True


def _no_new_security_violation(*, previous: SuiteReport, candidate: SuiteReport) -> bool:
    if candidate.treatment.policy_violations > previous.treatment.policy_violations:
        return False
    prev_forbidden = _forbidden_hit_total(previous.runs)
    cand_forbidden = _forbidden_hit_total(candidate.runs)
    return cand_forbidden <= prev_forbidden


def _case_id_for_failure(previous: SuiteReport, failure: Failure) -> str | None:
    for run in previous.runs:
        if run.id == failure.run_id:
            case_id = run.metrics.get("case_id")
            return str(case_id) if case_id is not None else None
    return None


def _treatment_success_by_case(runs: Sequence[EvaluationRun]) -> dict[str, float]:
    by_case: dict[str, list[bool]] = defaultdict(list)
    for run in runs:
        if run.baseline.get("baseline") is True:
            continue
        case_id = run.metrics.get("case_id")
        if case_id is None:
            continue
        by_case[str(case_id)].append(run.metrics.get("passed") is True)
    return {
        case_id: (sum(trials) / len(trials) if trials else 0.0)
        for case_id, trials in by_case.items()
    }


def _forbidden_hit_total(runs: Sequence[EvaluationRun]) -> int:
    total = 0
    for run in runs:
        if run.baseline.get("baseline") is True:
            continue
        total += _forbidden_hit_count(run.metrics)
    return total


def _forbidden_hit_count(metrics: Mapping[str, Any]) -> int:
    hits = metrics.get("forbidden_hits", 0)
    if isinstance(hits, list):
        return len(hits)
    if hits is None:
        return 0
    return int(hits)
