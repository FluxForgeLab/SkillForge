"""C8.1: PipelineRun advances only via ensure_pipeline_transition and emits events."""

from __future__ import annotations

import pytest

from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.domain.errors import InvalidStateTransition
from skillforge.domain.state_machines import PipelineState
from skillforge.orchestrator import PipelineRun
from skillforge.tracing.bus import EventBus


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


_HAPPY_PATH: list[PipelineState] = [
    PipelineState.EXTRACTED,
    PipelineState.DRAFTED,
    PipelineState.VALIDATING,
    PipelineState.CANDIDATE,
    PipelineState.EVALUATING,
    PipelineState.PASSED,
    PipelineState.APPROVED,
    PipelineState.PUBLISHED,
]


async def test_happy_path_ingested_to_published() -> None:
    sink = ListSink()
    run = PipelineRun("run_happy", sink=sink, bus=EventBus())
    assert run.state is PipelineState.INGESTED

    previous = PipelineState.INGESTED
    for target in _HAPPY_PATH:
        await run.advance(target)
        assert run.state is target
        event = sink.events[-1]
        assert event.type is TraceEventType.WORKFLOW_STARTED
        assert event.name == target.value
        assert event.stage == "orchestrator"
        assert event.run_id == "run_happy"
        assert event.output == {"previous": previous.value, "current": target.value}
        previous = target

    assert len(sink.events) == len(_HAPPY_PATH)


async def test_evaluating_to_failed_branch() -> None:
    sink = ListSink()
    run = PipelineRun("run_fail", sink=sink, bus=EventBus())
    for target in (
        PipelineState.EXTRACTED,
        PipelineState.DRAFTED,
        PipelineState.VALIDATING,
        PipelineState.CANDIDATE,
        PipelineState.EVALUATING,
    ):
        await run.advance(target)

    await run.advance(PipelineState.FAILED)
    assert run.state is PipelineState.FAILED
    event = sink.events[-1]
    assert event.type is TraceEventType.WORKFLOW_STARTED
    assert event.name == PipelineState.FAILED.value
    assert event.stage == "orchestrator"
    assert event.output == {
        "previous": PipelineState.EVALUATING.value,
        "current": PipelineState.FAILED.value,
    }


async def test_failed_cannot_advance_anywhere() -> None:
    sink = ListSink()
    run = PipelineRun("run_terminal", sink=sink, bus=EventBus())
    for target in (
        PipelineState.EXTRACTED,
        PipelineState.DRAFTED,
        PipelineState.VALIDATING,
        PipelineState.CANDIDATE,
        PipelineState.EVALUATING,
        PipelineState.FAILED,
    ):
        await run.advance(target)

    events_before = len(sink.events)
    for target in PipelineState:
        with pytest.raises(InvalidStateTransition) as exc_info:
            await run.advance(target)
        assert exc_info.value.machine == "pipeline"
        assert run.state is PipelineState.FAILED

    assert len(sink.events) == events_before
