"""C7.5: EvolutionGate five conditions + regression runner injection."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from skillforge.domain.entities import EvalCase, EvaluationRun, Failure
from skillforge.domain.enums import EvaluationRunStatus, FailureClass
from skillforge.evaluator.cases import LoadedEvalCase
from skillforge.evaluator.suite import ArmSummary, SuiteReport, summarize
from skillforge.evolution.gate import (
    GateCondition,
    evaluate_evolution_gate,
    run_regression,
)
from skillforge.tracing.sink import TraceSink


def test_gate_all_conditions_pass() -> None:
    previous = _suite(
        [
            _treatment("prev_f1", "eval_f1", passed=True),
            _treatment("prev_f2", "eval_f2", passed=True),
            _treatment("prev_f3", "eval_f3", passed=False),
            _control("prev_c1", "eval_f1", passed=False),
            _control("prev_c2", "eval_f2", passed=False),
            _control("prev_c3", "eval_f3", passed=False),
        ],
        version="ver_prev",
    )
    candidate = _suite(
        [
            _treatment("cand_f1", "eval_f1", passed=True),
            _treatment("cand_f2", "eval_f2", passed=True),
            _treatment("cand_f3", "eval_f3", passed=True),
            _control("cand_c1", "eval_f1", passed=False),
            _control("cand_c2", "eval_f2", passed=False),
            _control("cand_c3", "eval_f3", passed=False),
        ],
        version="ver_cand",
    )
    failure = _failure("prev_f3", source_support=["doc_runbook#page=2"])

    report = evaluate_evolution_gate(previous=previous, candidate=candidate, failure=failure)
    assert report.passed is True
    assert report.failed_conditions == []
    assert all(report.checks.values())


def test_gate_fails_when_success_rate_decreases() -> None:
    # Partial prior rates (< 1.0) so dropping them is not a "critical regression";
    # target f2 goes 0 → 1 while overall treatment rate still falls (9/11 → 1/11).
    previous = _suite(
        [
            *[_treatment(f"prev_f1_{i}", "eval_f1", passed=i < 9) for i in range(10)],
            _treatment("prev_f2", "eval_f2", passed=False),
            *[_control(f"prev_c1_{i}", "eval_f1", passed=False) for i in range(10)],
            _control("prev_c2", "eval_f2", passed=False),
        ],
        version="ver_prev",
    )
    candidate = _suite(
        [
            *[_treatment(f"cand_f1_{i}", "eval_f1", passed=False) for i in range(10)],
            _treatment("cand_f2", "eval_f2", passed=True),
            *[_control(f"cand_c1_{i}", "eval_f1", passed=False) for i in range(10)],
            _control("cand_c2", "eval_f2", passed=False),
        ],
        version="ver_cand",
    )
    failure = _failure("prev_f2", source_support=["doc#1"])

    report = evaluate_evolution_gate(previous=previous, candidate=candidate, failure=failure)
    assert report.passed is False
    assert report.failed_conditions == [GateCondition.SUCCESS_RATE_NON_DECREASING]
    assert report.checks[GateCondition.SUCCESS_RATE_NON_DECREASING.value] is False
    assert report.checks[GateCondition.NO_CRITICAL_REGRESSION.value] is True
    assert report.checks[GateCondition.TARGET_FAILURE_FIXED.value] is True


def test_gate_fails_when_target_failure_not_fixed() -> None:
    previous = _suite(
        [
            _treatment("prev_f1", "eval_f1", passed=True),
            _treatment("prev_f3", "eval_f3", passed=False),
            _control("prev_c1", "eval_f1", passed=False),
            _control("prev_c3", "eval_f3", passed=False),
        ],
        version="ver_prev",
    )
    candidate = _suite(
        [
            _treatment("cand_f1", "eval_f1", passed=True),
            _treatment("cand_f3", "eval_f3", passed=False),
            _control("cand_c1", "eval_f1", passed=False),
            _control("cand_c3", "eval_f3", passed=False),
        ],
        version="ver_cand",
    )
    failure = _failure("prev_f3", source_support=["doc#1"])

    report = evaluate_evolution_gate(previous=previous, candidate=candidate, failure=failure)
    assert report.passed is False
    assert report.failed_conditions == [GateCondition.TARGET_FAILURE_FIXED]
    assert report.checks[GateCondition.TARGET_FAILURE_FIXED.value] is False


def test_gate_fails_on_critical_regression() -> None:
    # Same overall rate (2/3), target f3 fixed, but previously-passing f2 drops.
    previous = _suite(
        [
            _treatment("prev_f1", "eval_f1", passed=True),
            _treatment("prev_f2", "eval_f2", passed=True),
            _treatment("prev_f3", "eval_f3", passed=False),
            _control("prev_c1", "eval_f1", passed=False),
            _control("prev_c2", "eval_f2", passed=False),
            _control("prev_c3", "eval_f3", passed=False),
        ],
        version="ver_prev",
    )
    candidate = _suite(
        [
            _treatment("cand_f1", "eval_f1", passed=True),
            _treatment("cand_f2", "eval_f2", passed=False),
            _treatment("cand_f3", "eval_f3", passed=True),
            _control("cand_c1", "eval_f1", passed=False),
            _control("cand_c2", "eval_f2", passed=False),
            _control("cand_c3", "eval_f3", passed=False),
        ],
        version="ver_cand",
    )
    failure = _failure("prev_f3", source_support=["doc#1"])

    report = evaluate_evolution_gate(previous=previous, candidate=candidate, failure=failure)
    assert report.passed is False
    assert report.failed_conditions == [GateCondition.NO_CRITICAL_REGRESSION]
    assert report.checks[GateCondition.NO_CRITICAL_REGRESSION.value] is False
    # Overall rate unchanged (2/3), so success_rate condition still passes.
    assert report.checks[GateCondition.SUCCESS_RATE_NON_DECREASING.value] is True
    assert report.checks[GateCondition.TARGET_FAILURE_FIXED.value] is True


def test_gate_fails_on_new_security_violation() -> None:
    previous = _suite(
        [
            _treatment("prev_f1", "eval_f1", passed=True, policy=0, forbidden=0),
            _treatment("prev_f3", "eval_f3", passed=False, policy=0, forbidden=0),
            _control("prev_c1", "eval_f1", passed=False),
            _control("prev_c3", "eval_f3", passed=False),
        ],
        version="ver_prev",
    )
    candidate = _suite(
        [
            _treatment("cand_f1", "eval_f1", passed=True, policy=0, forbidden=0),
            _treatment("cand_f3", "eval_f3", passed=True, policy=1, forbidden=1),
            _control("cand_c1", "eval_f1", passed=False),
            _control("cand_c3", "eval_f3", passed=False),
        ],
        version="ver_cand",
    )
    failure = _failure("prev_f3", source_support=["doc#1"])

    report = evaluate_evolution_gate(previous=previous, candidate=candidate, failure=failure)
    assert report.passed is False
    assert report.failed_conditions == [GateCondition.NO_NEW_SECURITY_VIOLATION]
    assert report.checks[GateCondition.NO_NEW_SECURITY_VIOLATION.value] is False


def test_gate_fails_when_source_evidence_missing() -> None:
    previous = _suite(
        [
            _treatment("prev_f1", "eval_f1", passed=True),
            _treatment("prev_f3", "eval_f3", passed=False),
            _control("prev_c1", "eval_f1", passed=False),
            _control("prev_c3", "eval_f3", passed=False),
        ],
        version="ver_prev",
    )
    candidate = _suite(
        [
            _treatment("cand_f1", "eval_f1", passed=True),
            _treatment("cand_f3", "eval_f3", passed=True),
            _control("cand_c1", "eval_f1", passed=False),
            _control("cand_c3", "eval_f3", passed=False),
        ],
        version="ver_cand",
    )
    failure = _failure("prev_f3", source_support=[])

    report = evaluate_evolution_gate(previous=previous, candidate=candidate, failure=failure)
    assert report.passed is False
    assert report.failed_conditions == [GateCondition.SOURCE_EVIDENCE_EXISTS]
    assert report.checks[GateCondition.SOURCE_EVIDENCE_EXISTS.value] is False


async def test_run_regression_uses_injected_suite_runner(tmp_path: Path) -> None:
    expected = SuiteReport(
        skill_version_id="ver_fake",
        repeats=1,
        uplift_pp=0.0,
        control=ArmSummary(
            baseline=True,
            trials=1,
            success_rate=0.0,
            avg_latency=0.0,
            tool_error_count=0,
            policy_violations=0,
        ),
        treatment=ArmSummary(
            baseline=False,
            trials=1,
            success_rate=1.0,
            avg_latency=10.0,
            tool_error_count=0,
            policy_violations=0,
        ),
        runs=[],
    )
    called: list[str] = []

    async def fake_runner(*_args: object, **kwargs: object) -> SuiteReport:
        called.append(str(kwargs["skill_version_id"]))
        return expected

    def factory(run_id: str, sink: TraceSink) -> object:
        del run_id, sink
        raise AssertionError("harness must not run when suite_runner is injected")

    report = await run_regression(
        [_loaded_case()],
        skill_path="skills/candidate",
        skill_version_id="ver_fake",
        workspace=str(tmp_path),
        harness_factory=factory,  # type: ignore[arg-type]
        db_path=tmp_path / "unused.sqlite",
        suite_runner=fake_runner,
    )
    assert report is expected
    assert called == ["ver_fake"]


def _suite(runs: list[EvaluationRun], *, version: str) -> SuiteReport:
    return summarize(runs, skill_version_id=version, repeats=1)


def _failure(run_id: str, *, source_support: list[str]) -> Failure:
    return Failure(
        run_id=run_id,
        failure_class=FailureClass.MISSING_INSTRUCTION,
        symptom="target case still failing",
        failed_assertion="http_status",
        evidence=["trace snippet"],
        source_support=source_support,
    )


def _treatment(
    run_id: str,
    case_id: str,
    *,
    passed: bool,
    policy: int = 0,
    forbidden: int = 0,
) -> EvaluationRun:
    return _run(
        run_id,
        case_id,
        baseline=False,
        passed=passed,
        policy=policy,
        forbidden=forbidden,
    )


def _control(run_id: str, case_id: str, *, passed: bool) -> EvaluationRun:
    return _run(run_id, case_id, baseline=True, passed=passed, policy=0, forbidden=0)


def _run(
    run_id: str,
    case_id: str,
    *,
    baseline: bool,
    passed: bool,
    policy: int,
    forbidden: int,
) -> EvaluationRun:
    now = datetime.now(UTC)
    return EvaluationRun(
        id=run_id,
        skill_version_id="ver",
        baseline={"baseline": baseline},
        metrics={
            "case_id": case_id,
            "passed": passed,
            "latency_ms": 10,
            "tool_errors": 0,
            "policy_violations": policy,
            "forbidden_hits": forbidden,
        },
        status=EvaluationRunStatus.COMPLETED,
        started_at=now,
        finished_at=now,
    )


def _loaded_case() -> LoadedEvalCase:
    case = EvalCase(
        id="eval_backend_stopped",
        name="backend process stopped",
        task="Restore it.",
        fixture="backend_stopped",
        expected={"http_status": 200},
        forbidden=["delete_volume"],
        timeout_sec=30,
    )
    return LoadedEvalCase(case=case, fault_id="backend_stopped")
