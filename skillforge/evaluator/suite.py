"""Control versus treatment suite and skill uplift."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from skillforge.domain.entities import EvaluationRun, TraceEvent
from skillforge.evaluator.cache import replay_trials, store_trial
from skillforge.evaluator.cases import LoadedEvalCase
from skillforge.evaluator.runner import _SETTLE_SEC, InjectFn, ResetFn, VerifyFn, run_case
from skillforge.runtime.agent import AgentRuntime
from skillforge.tracing.sink import TraceSink

HarnessFactory = Callable[[str, TraceSink], AgentRuntime]


class MemorySink:
    """In-memory trace sink for one suite trial."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


class ArmSummary(BaseModel):
    """Aggregates for one arm of a suite."""

    model_config = ConfigDict(extra="forbid")

    baseline: bool
    trials: int
    success_rate: float
    avg_latency: float
    tool_error_count: int
    policy_violations: int


class SuiteReport(BaseModel):
    """Suite-level uplift. Each trial remains its own EvaluationRun row."""

    model_config = ConfigDict(extra="forbid")

    skill_version_id: str
    repeats: int
    uplift_pp: float
    control: ArmSummary
    treatment: ArmSummary
    runs: list[EvaluationRun]


def summarize(runs: Sequence[EvaluationRun], *, skill_version_id: str, repeats: int) -> SuiteReport:
    """Aggregate passed trials, latency, tool errors, and policy violations."""
    control_runs = [run for run in runs if run.baseline.get("baseline") is True]
    treatment_runs = [run for run in runs if run.baseline.get("baseline") is not True]
    control = _arm_summary(control_runs, baseline=True, label="control")
    treatment = _arm_summary(treatment_runs, baseline=False, label="treatment")
    return SuiteReport(
        skill_version_id=skill_version_id,
        repeats=repeats,
        uplift_pp=(treatment.success_rate - control.success_rate) * 100,
        control=control,
        treatment=treatment,
        runs=list(runs),
    )


async def run_suite(
    cases: Sequence[LoadedEvalCase],
    *,
    skill_path: str,
    skill_version_id: str,
    workspace: str,
    harness_factory: HarnessFactory,
    db_path: Path,
    repeats: int = 1,
    suite_id: str | None = None,
    reset: ResetFn | None = None,
    inject: InjectFn | None = None,
    verify: VerifyFn | None = None,
    settle_sec: float = _SETTLE_SEC,
    version_hash: str | None = None,
    model: str | None = None,
    replay: bool = False,
) -> SuiteReport:
    """Run control then treatment for each case and repeat.

    ``harness_factory`` must attach the given sink and run_id, and use the same settings
    and default tool registry for every call. Control passes ``skill_path=None``.
    When ``replay`` is True, trials are loaded from ``eval_cache`` and the harness is unused.
    """
    if repeats < 1:
        raise ValueError(f"repeats must be >= 1, got {repeats}")
    if replay:
        if version_hash is None or model is None:
            raise ValueError("version_hash and model are required when replay=True")
        case_ids = [loaded.case.id for loaded in cases]
        runs = replay_trials(
            db_path,
            version_hash=version_hash,
            model=model,
            case_ids=case_ids,
        )
        return summarize(runs, skill_version_id=skill_version_id, repeats=repeats)

    prefix = suite_id if suite_id is not None else f"suite_{uuid4().hex}"
    runs: list[EvaluationRun] = []
    for case in cases:
        for index in range(repeats):
            for baseline, arm in ((True, "control"), (False, "treatment")):
                run_id = f"{prefix}_{case.case.id}_{arm}_{index}"
                sink = MemorySink()
                harness = harness_factory(run_id, sink)
                record = await run_case(
                    case,
                    run_id=run_id,
                    skill_path=None if baseline else skill_path,
                    skill_version_id=skill_version_id,
                    workspace=workspace,
                    harness=harness,
                    sink=sink,
                    db_path=db_path,
                    reset=reset,
                    inject=inject,
                    verify=verify,
                    settle_sec=settle_sec,
                    baseline=baseline,
                    evals_dir=skill_path,
                )
                runs.append(record)
                if version_hash is not None and model is not None:
                    store_trial(
                        db_path,
                        version_hash=version_hash,
                        case_id=str(record.metrics["case_id"]),
                        arm="control" if record.baseline["baseline"] is True else "treatment",
                        model=model,
                        baseline=bool(record.baseline["baseline"]),
                        metrics=dict(record.metrics),
                        status=record.status.value,
                    )
    return summarize(runs, skill_version_id=skill_version_id, repeats=repeats)


def _arm_summary(runs: Sequence[EvaluationRun], *, baseline: bool, label: str) -> ArmSummary:
    if not runs:
        raise ValueError(f"{label} arm has no trials")
    passed = sum(1 for run in runs if run.metrics.get("passed") is True)
    latency = sum(int(run.metrics.get("latency_ms", 0)) for run in runs)
    tool_errors = sum(int(run.metrics.get("tool_errors", 0)) for run in runs)
    violations = sum(int(run.metrics.get("policy_violations", 0)) for run in runs)
    trials = len(runs)
    return ArmSummary(
        baseline=baseline,
        trials=trials,
        success_rate=passed / trials,
        avg_latency=latency / trials,
        tool_error_count=tool_errors,
        policy_violations=violations,
    )
