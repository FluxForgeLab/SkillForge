"""F1 recovery with a scripted model. Requires ops-lab and the sandbox image."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docker
from skillforge.config import Settings, get_settings
from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse, TokenUsage, ToolCall
from skillforge.runtime.agent import LocalHarness
from skillforge.tracing.bus import EventBus
from tests.integration.support_ops_lab import load_fault_modules, wait_until_healthy

_IMAGE_CONTEXT = Path(__file__).resolve().parents[2] / "docker" / "sandbox"
_SKILL = Path(__file__).resolve().parents[2] / "skills" / "golden" / "service-recovery"
_TASK = "The web service returns 502. Restore it and verify recovery."


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


@pytest.fixture(scope="session")
def sandbox_image(docker_available: None) -> str:
    client = docker.from_env()
    image = get_settings().sandbox_image
    try:
        _built, logs = client.images.build(path=str(_IMAGE_CONTEXT), tag=image, rm=True)
        for _item in logs:
            pass
    finally:
        client.close()
    return image


def _call(name: str, arguments: dict, call_id: str) -> ModelResponse:
    return ModelResponse(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=json.dumps(arguments))],
        finish_reason="tool_calls",
        usage=TokenUsage(total_tokens=1),
    )


def _script() -> list[ModelResponse]:
    return [
        _call("docker.inspect", {"service": "backend"}, "call_inspect"),
        _call("docker.logs", {"service": "backend", "tail": 100}, "call_logs"),
        _call("docker.restart", {"service": "backend"}, "call_restart"),
        _call("http.get", {"url": "http://127.0.0.1:8088/health"}, "call_health"),
        ModelResponse(content="recovered", finish_reason="stop", usage=TokenUsage(total_tokens=1)),
    ]


@pytest.mark.integration
async def test_f1_recovered_with_scripted_model(
    tmp_path: Path,
    ops_lab: None,
    ops_lab_verifier,
    sandbox_image: str,
) -> None:
    del ops_lab, sandbox_image
    _catalog, inject, reset = load_fault_modules()
    inject.inject("backend_stopped")
    sink = ListSink()
    settings = Settings(max_steps=8, max_seconds=120, temperature=0.0)
    gateway = ModelGateway(
        FakeModelAdapter(_script()),
        settings=settings,
        sink=sink,
        bus=EventBus(),
    )
    harness = LocalHarness(
        gateway=gateway,
        settings=settings,
        sink=sink,
        bus=EventBus(),
        run_id="run_c39",
    )
    try:
        result = await harness.run(_TASK, str(_SKILL), str(tmp_path))
        assert result.status == "completed"
        assert result.tool_errors == 0
        assert result.policy_violations == 0
        calls = [
            (event.name, event.input)
            for event in sink.events
            if event.type == TraceEventType.TOOL_CALL
        ]
        assert calls == [
            ("docker.inspect", {"service": "backend"}),
            ("docker.logs", {"service": "backend", "tail": 100}),
            ("docker.restart", {"service": "backend"}),
            ("http.get", {"url": "http://127.0.0.1:8088/health"}),
        ]
        wait_until_healthy(ops_lab_verifier, timeout=30.0)
    finally:
        reset.reset()
