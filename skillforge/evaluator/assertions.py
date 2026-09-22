"""Compare verifier output and trace events against an eval case."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from skillforge.domain.entities import EvalCase, TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.tracing.bus import EventBus
from skillforge.tracing.emitter import emit
from skillforge.tracing.sink import TraceSink


class FieldMismatch(BaseModel):
    """One expected field that is missing or different in the verifier output."""

    model_config = ConfigDict(extra="forbid")

    field: str
    expected: Any
    actual: Any = None


class AssertionResult(BaseModel):
    """Deterministic pass or fail for a single eval case."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    mismatches: list[FieldMismatch]
    forbidden_hits: list[str]


async def assert_case(
    case: EvalCase,
    verifier: Mapping[str, Any],
    events: Sequence[TraceEvent],
    *,
    run_id: str,
    sink: TraceSink,
) -> AssertionResult:
    """Check expected fields and forbidden actions, then emit one assertion event."""
    mismatches = _mismatches(case.expected, verifier)
    hits = _forbidden_hits(case.forbidden, events)
    result = AssertionResult(
        passed=not mismatches and not hits,
        mismatches=mismatches,
        forbidden_hits=hits,
    )
    await emit(
        run_id,
        TraceEventType.ASSERTION,
        name=case.id,
        input={"expected": case.expected, "forbidden": list(case.forbidden)},
        output={
            "passed": result.passed,
            "mismatches": [item.model_dump() for item in result.mismatches],
            "forbidden_hits": result.forbidden_hits,
        },
        stage="evaluator",
        sink=sink,
        bus=EventBus(),
    )
    return result


def _mismatches(expected: Mapping[str, Any], verifier: Mapping[str, Any]) -> list[FieldMismatch]:
    mismatches: list[FieldMismatch] = []
    for field, want in expected.items():
        if field not in verifier:
            mismatches.append(FieldMismatch(field=field, expected=want, actual=None))
            continue
        actual = verifier[field]
        if not _values_equal(want, actual):
            mismatches.append(FieldMismatch(field=field, expected=want, actual=actual))
    return mismatches


def _values_equal(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(expected) is type(actual) and expected == actual
    return expected == actual


def _forbidden_hits(forbidden: Sequence[str], events: Sequence[TraceEvent]) -> list[str]:
    banned = set(forbidden)
    hits: list[str] = []
    seen: set[str] = set()
    for event in events:
        name = _forbidden_name(event, banned)
        if name is None or name in seen:
            continue
        seen.add(name)
        hits.append(name)
    return hits


def _forbidden_name(event: TraceEvent, banned: set[str]) -> str | None:
    if event.type == TraceEventType.TOOL_CALL and event.name in banned:
        return event.name
    if event.type != TraceEventType.POLICY_VIOLATION:
        return None
    output_name = event.output.get("name")
    if isinstance(output_name, str) and output_name in banned:
        return output_name
    return None
