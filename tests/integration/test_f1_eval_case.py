"""C4.3: golden skill recovers F1 through the single-case runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import docker
from skillforge.config import Settings, get_settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.evaluation_runs import get_evaluation_run
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.skill_versions import insert_skill_version
from skillforge.db.repositories.skills import insert_skill
from skillforge.domain.entities import Project, Skill, SkillVersion, TraceEvent
from skillforge.domain.enums import EvaluationRunStatus, TraceEventType
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.evaluator import load_eval_cases, run_case
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse, TokenUsage, ToolCall
from skillforge.runtime.agent import LocalHarness
from skillforge.tracing.bus import EventBus
from tests.integration.support_ops_lab import wait_until_healthy

_IMAGE_CONTEXT = Path(__file__).resolve().parents[2] / "docker" / "sandbox"
_SKILL = Path(__file__).resolve().parents[2] / "skills" / "golden" / "service-recovery"
_RUN_ID = "evalrun_f1"


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
async def test_f1_golden_case_passes(
    tmp_path: Path,
    ops_lab: None,
    ops_lab_verifier,
    sandbox_image: str,
) -> None:
    del ops_lab, sandbox_image
    db_path = tmp_path / "eval.sqlite"
    version_id = _seed(db_path)
    loaded = next(item for item in load_eval_cases(_SKILL) if item.fault_id == "backend_stopped")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
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
        run_id=_RUN_ID,
    )
    record = await run_case(
        loaded,
        run_id=_RUN_ID,
        skill_path=str(_SKILL),
        skill_version_id=version_id,
        workspace=str(workspace),
        harness=harness,
        sink=sink,
        db_path=db_path,
    )
    assert record.status == EvaluationRunStatus.COMPLETED
    assert record.metrics["passed"] is True
    assert record.metrics["timed_out"] is False
    assert record.metrics["case_id"] == "eval_backend_stopped"
    assert record.baseline == {"baseline": False}
    calls = [
        (event.name, event.input) for event in sink.events if event.type == TraceEventType.TOOL_CALL
    ]
    assert calls == [
        ("docker.inspect", {"service": "backend"}),
        ("docker.logs", {"service": "backend", "tail": 100}),
        ("docker.restart", {"service": "backend"}),
        ("http.get", {"url": "http://127.0.0.1:8088/health"}),
    ]
    assertions = [event for event in sink.events if event.type == TraceEventType.ASSERTION]
    assert len(assertions) == 1
    assert assertions[0].output["passed"] is True
    assert assertions[0].run_id == _RUN_ID
    with connection(db_path) as conn:
        stored = get_evaluation_run(conn, _RUN_ID)
    assert stored is not None
    assert stored.model_dump() == record.model_dump()
    wait_until_healthy(ops_lab_verifier, timeout=30.0)


def _seed(db_path: Path) -> str:
    initialize_database(db_path)
    now = datetime.now(UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id="proj_f1", name="lab", created_at=now))
        insert_skill(
            conn,
            Skill(id="skill_f1", project_id="proj_f1", name="service-recovery"),
        )
        insert_skill_version(
            conn,
            SkillVersion(
                id="ver_f1",
                skill_id="skill_f1",
                version="0.1",
                status=SkillVersionStatus.DRAFT,
                artifact_path=str(_SKILL),
                created_at=now,
            ),
        )
    return "ver_f1"
