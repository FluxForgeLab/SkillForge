"""C4.4: one F1 case, control and treatment, same scripted model."""

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
from skillforge.domain.entities import Project, Skill, SkillVersion
from skillforge.domain.enums import EvaluationRunStatus, TraceEventType
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.evaluator import load_eval_cases, run_suite
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse, TokenUsage, ToolCall
from skillforge.runtime.agent import LocalHarness
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import TraceSink
from tests.integration.support_ops_lab import wait_until_healthy

_IMAGE_CONTEXT = Path(__file__).resolve().parents[2] / "docker" / "sandbox"
_SKILL = Path(__file__).resolve().parents[2] / "skills" / "golden" / "service-recovery"
_TOOL_CALLS = [
    ("docker.inspect", {"service": "backend"}),
    ("docker.logs", {"service": "backend", "tail": 100}),
    ("docker.restart", {"service": "backend"}),
    ("http.get", {"url": "http://127.0.0.1:8088/health"}),
]


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
async def test_f1_control_and_treatment(
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
    settings = Settings(max_steps=8, max_seconds=120, temperature=0.0)
    sinks: dict[str, TraceSink] = {}

    def factory(run_id: str, sink: TraceSink) -> LocalHarness:
        sinks[run_id] = sink
        gateway = ModelGateway(
            FakeModelAdapter(_script()),
            settings=settings,
            sink=sink,
            bus=EventBus(),
        )
        return LocalHarness(
            gateway=gateway,
            settings=settings,
            sink=sink,
            bus=EventBus(),
            run_id=run_id,
        )

    report = await run_suite(
        [loaded],
        skill_path=str(_SKILL),
        skill_version_id=version_id,
        workspace=str(workspace),
        harness_factory=factory,
        db_path=db_path,
        repeats=1,
        suite_id="suite_f1",
    )
    assert report.uplift_pp == 0
    assert report.control.baseline is True
    assert report.treatment.baseline is False
    assert report.control.success_rate == 1
    assert report.treatment.success_rate == 1
    assert [run.baseline["baseline"] for run in report.runs] == [True, False]
    assert all(run.status == EvaluationRunStatus.COMPLETED for run in report.runs)
    control, treatment = report.runs
    assert "# Skill" not in _system_prompt(sinks[control.id])
    assert "# Skill" in _system_prompt(sinks[treatment.id])
    assert _tool_calls(sinks[control.id]) == _TOOL_CALLS
    assert _tool_calls(sinks[treatment.id]) == _TOOL_CALLS
    with connection(db_path) as conn:
        stored_control = get_evaluation_run(conn, control.id)
        stored_treatment = get_evaluation_run(conn, treatment.id)
    assert stored_control is not None and stored_control.baseline == {"baseline": True}
    assert stored_treatment is not None and stored_treatment.baseline == {"baseline": False}
    wait_until_healthy(ops_lab_verifier, timeout=30.0)


def _system_prompt(sink: TraceSink) -> str:
    events = getattr(sink, "events", [])
    for event in events:
        if event.type != TraceEventType.MODEL_REQUEST:
            continue
        for message in event.input["messages"]:
            if message["role"] == "system":
                return str(message["content"])
    raise AssertionError("missing system prompt")


def _tool_calls(sink: TraceSink) -> list[tuple[str | None, object]]:
    events = getattr(sink, "events", [])
    return [(event.name, event.input) for event in events if event.type == TraceEventType.TOOL_CALL]


def _seed(db_path: Path) -> str:
    initialize_database(db_path)
    now = datetime.now(UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id="proj_ab", name="lab", created_at=now))
        insert_skill(conn, Skill(id="skill_ab", project_id="proj_ab", name="service-recovery"))
        insert_skill_version(
            conn,
            SkillVersion(
                id="ver_ab",
                skill_id="skill_ab",
                version="0.1",
                status=SkillVersionStatus.DRAFT,
                artifact_path=str(_SKILL),
                created_at=now,
            ),
        )
    return "ver_ab"
