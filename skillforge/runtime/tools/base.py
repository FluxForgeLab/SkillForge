"""Tool specs and the registry that records every call."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from skillforge.domain.enums import TraceEventType
from skillforge.domain.errors import PolicyViolation
from skillforge.models.types import ToolDefinition
from skillforge.sandbox.base import Sandbox
from skillforge.sandbox.policy import SandboxPolicy
from skillforge.tracing.bus import EventBus
from skillforge.tracing.emitter import emit
from skillforge.tracing.sink import TraceSink

TOOL_TIMEOUT_SEC = 10.0

ToolHandler = Callable[["ToolContext", dict[str, Any]], Awaitable[dict[str, Any]]]


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any]
    permissions: list[str]

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )


@dataclass
class ToolContext:
    sandbox: Sandbox
    policy: SandboxPolicy
    opslab_base_url: str
    timeout_sec: float = TOOL_TIMEOUT_SEC


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def specs(self) -> list[ToolSpec]:
        return [self._specs[name] for name in self._specs]

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise KeyError(name) from None

    async def call(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: ToolContext,
        *,
        run_id: str,
        sink: TraceSink | None = None,
        bus: EventBus | None = None,
    ) -> dict[str, Any]:
        try:
            handler = self._handlers[name]
        except KeyError:
            raise KeyError(name) from None
        await emit(
            run_id,
            TraceEventType.TOOL_CALL,
            name=name,
            input=arguments,
            stage="runtime",
            sink=sink,
            bus=bus,
        )
        try:
            result = await handler(ctx, arguments)
        except PolicyViolation as exc:
            await emit(
                run_id,
                TraceEventType.POLICY_VIOLATION,
                name=name,
                input=arguments,
                output={"kind": exc.kind, "name": exc.name, "detail": exc.detail},
                stage="runtime",
                sink=sink,
                bus=bus,
            )
            raise
        await emit(
            run_id,
            TraceEventType.TOOL_RESULT,
            name=name,
            output=result,
            stage="runtime",
            sink=sink,
            bus=bus,
        )
        return result
