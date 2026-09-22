"""LocalHarness ReAct loop. Skill parsing stays in the prompt module."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from skillforge.config import Settings
from skillforge.domain.errors import PolicyViolation
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ChatMessage, ModelRequest, ToolCall
from skillforge.runtime.prompt import system_prompt
from skillforge.runtime.tools import ToolContext, ToolRegistry, runtime_tools
from skillforge.sandbox.base import Sandbox
from skillforge.sandbox.policy import SandboxPolicy, load_default_policy
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import TraceSink

RunStatus = Literal["completed", "exhausted"]


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    final_content: str | None
    steps: int
    tool_errors: int
    tokens: int
    latency_ms: int
    policy_violations: int


class AgentRuntime(Protocol):
    async def run(self, task: str, skill_path: str | None, workspace: str) -> RunResult: ...


class LocalHarness:
    def __init__(
        self,
        *,
        gateway: ModelGateway,
        settings: Settings,
        registry: ToolRegistry | None = None,
        sandbox: Sandbox | None = None,
        policy: SandboxPolicy | None = None,
        sink: TraceSink | None = None,
        bus: EventBus | None = None,
        run_id: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._settings = settings
        self._registry = registry if registry is not None else runtime_tools()
        self._sandbox = sandbox
        self._policy = policy if policy is not None else load_default_policy()
        self._sink = sink
        self._bus = bus
        self._run_id = run_id

    async def run(self, task: str, skill_path: str | None, workspace: str) -> RunResult:
        run_id = self._run_id or f"run_{uuid4().hex}"
        sandbox = (
            self._sandbox
            if self._sandbox is not None
            else _docker_sandbox(run_id, self._sink, self._bus)
        )
        started = time.perf_counter()
        try:
            await sandbox.create(policy=self._policy, workspace=Path(workspace))
            return await self._loop(
                task,
                skill_path,
                sandbox,
                run_id=run_id,
                started=started,
            )
        finally:
            await sandbox.destroy()

    async def _loop(
        self,
        task: str,
        skill_path: str | None,
        sandbox: Sandbox,
        *,
        run_id: str,
        started: float,
    ) -> RunResult:
        messages = [
            ChatMessage(role="system", content=system_prompt(skill_path)),
            ChatMessage(role="user", content=task),
        ]
        tools = [spec.definition() for spec in self._registry.specs()]
        ctx = ToolContext(
            sandbox=sandbox,
            policy=self._policy,
            opslab_base_url=self._settings.opslab_base_url,
        )
        steps = 0
        tool_errors = 0
        policy_violations = 0
        tokens = 0
        while True:
            if self._budget_exhausted(steps, started):
                return self._result(
                    run_id,
                    "exhausted",
                    None,
                    steps,
                    tool_errors,
                    tokens,
                    policy_violations,
                    started,
                )
            response = await self._gateway.generate(
                ModelRequest(
                    run_id=run_id,
                    messages=messages,
                    tools=tools,
                    temperature=self._settings.temperature,
                    seed=self._settings.seed,
                    stage="runtime",
                )
            )
            steps += 1
            tokens += response.usage.total_tokens
            if not response.tool_calls:
                return self._result(
                    run_id,
                    "completed",
                    response.content,
                    steps,
                    tool_errors,
                    tokens,
                    policy_violations,
                    started,
                )
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for call in response.tool_calls:
                content, errors, violations = await self._execute_call(call, ctx, run_id)
                tool_errors += errors
                policy_violations += violations
                messages.append(
                    ChatMessage(role="tool", content=content, tool_call_id=call.id),
                )

    def _budget_exhausted(self, steps: int, started: float) -> bool:
        if steps >= self._settings.max_steps:
            return True
        elapsed = time.perf_counter() - started
        return elapsed >= self._settings.max_seconds

    async def _execute_call(
        self,
        call: ToolCall,
        ctx: ToolContext,
        run_id: str,
    ) -> tuple[str, int, int]:
        try:
            arguments = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            return json.dumps({"error": "invalid arguments"}), 1, 0
        if not isinstance(arguments, dict):
            return json.dumps({"error": "invalid arguments"}), 1, 0
        try:
            result = await self._registry.call(
                call.name,
                arguments,
                ctx,
                run_id=run_id,
                sink=self._sink,
                bus=self._bus,
            )
        except PolicyViolation as exc:
            payload = {"error": str(exc), "policy_violation": True}
            return json.dumps(payload), 0, 1
        except KeyError:
            return json.dumps({"error": f"unknown tool {call.name}"}), 1, 0
        except Exception as exc:
            return json.dumps({"error": str(exc)}), 1, 0
        return json.dumps(result), 0, 0

    def _result(
        self,
        run_id: str,
        status: RunStatus,
        final_content: str | None,
        steps: int,
        tool_errors: int,
        tokens: int,
        policy_violations: int,
        started: float,
    ) -> RunResult:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return RunResult(
            run_id=run_id,
            status=status,
            final_content=final_content,
            steps=steps,
            tool_errors=tool_errors,
            tokens=tokens,
            latency_ms=latency_ms,
            policy_violations=policy_violations,
        )


def _docker_sandbox(run_id: str, sink: TraceSink | None, bus: EventBus | None) -> Sandbox:
    from skillforge.sandbox.docker import DockerSandbox

    return DockerSandbox(run_id=run_id, sink=sink, bus=bus)
