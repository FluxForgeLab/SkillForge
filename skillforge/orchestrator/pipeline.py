"""In-memory PipelineRun driven by the domain transition table."""

from __future__ import annotations

from skillforge.domain.enums import TraceEventType
from skillforge.domain.state_machines import PipelineState, ensure_pipeline_transition
from skillforge.tracing.bus import EventBus
from skillforge.tracing.emitter import emit
from skillforge.tracing.sink import TraceSink


class PipelineRun:
    """Advances through PipelineState, emitting a workflow_started event per step."""

    def __init__(
        self,
        run_id: str,
        *,
        sink: TraceSink,
        bus: EventBus | None = None,
    ) -> None:
        self.run_id = run_id
        self.state = PipelineState.INGESTED
        self._sink = sink
        self._bus = bus

    async def advance(self, target: PipelineState) -> None:
        """Move to target if legal; emit WORKFLOW_STARTED; else raise InvalidStateTransition."""
        previous = self.state
        ensure_pipeline_transition(previous, target)
        self.state = target
        await emit(
            self.run_id,
            TraceEventType.WORKFLOW_STARTED,
            name=target.value,
            stage="orchestrator",
            output={"previous": previous.value, "current": target.value},
            bus=self._bus,
            sink=self._sink,
        )
