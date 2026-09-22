"""C4.6: POST evaluate as background job; GET stored evaluation run."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from starlette.testclient import TestClient

from skillforge.api.main import create_app
from skillforge.api.routers.evaluations import get_evaluate_runner
from skillforge.config import Settings
from skillforge.db import initialize_database
from skillforge.db.connection import connection
from skillforge.db.repositories.evaluation_runs import insert_evaluation_run
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.skill_versions import insert_skill_version
from skillforge.db.repositories.skills import insert_skill
from skillforge.domain.entities import EvaluationRun, Project, Skill, SkillVersion, TraceEvent
from skillforge.domain.enums import EvaluationRunStatus, TraceEventType
from skillforge.domain.state_machines import SkillVersionStatus
from skillforge.tracing.bus import EventBus


def _seed(
    db_path: Path,
    *,
    skill_id: str = "skill_eval",
    version_id: str = "ver_eval",
    artifact_path: str = "skills/dummy/service-recovery",
    current: bool = True,
) -> None:
    now = datetime.now(UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id="proj_eval", name="lab", created_at=now))
        insert_skill(
            conn,
            Skill(
                id=skill_id,
                project_id="proj_eval",
                name="service-recovery",
                current_version_id=version_id if current else None,
            ),
        )
        insert_skill_version(
            conn,
            SkillVersion(
                id=version_id,
                skill_id=skill_id,
                version="0.1",
                status=SkillVersionStatus.DRAFT,
                artifact_path=artifact_path,
                created_at=now,
            ),
        )


def _client(
    tmp_path: Path,
    bus: EventBus,
    runner,
) -> tuple[TestClient, Path, Settings]:
    db_path = tmp_path / "api_evaluate.db"
    initialize_database(db_path)
    settings = Settings(_env_file=None, sqlite_path=db_path)
    app = create_app(settings, bus=bus)
    app.dependency_overrides[get_evaluate_runner] = lambda: runner
    return TestClient(app), db_path, settings


def test_evaluate_returns_job_id_and_emits_bus_events(tmp_path: Path) -> None:
    bus = EventBus()
    collected: list[TraceEvent] = []

    async def collect(event: TraceEvent) -> None:
        collected.append(event)

    bus.subscribe(collect)

    async def fake_runner(
        *,
        skill_id: str,
        skill_version_id: str,
        skill_dir: str,
        repeats: int,
        settings: Settings,
        bus: EventBus,
    ) -> list[str]:
        assert skill_id == "skill_eval"
        assert skill_version_id == "ver_eval"
        assert skill_dir == "skills/dummy/service-recovery"
        assert repeats == 1
        run_id = "eval_run_1"
        now = datetime.now(UTC)
        with connection(settings.sqlite_path) as conn:
            insert_evaluation_run(
                conn,
                EvaluationRun(
                    id=run_id,
                    skill_version_id=skill_version_id,
                    baseline={"baseline": False},
                    metrics={"passed": True, "latency_ms": 12},
                    status=EvaluationRunStatus.COMPLETED,
                    started_at=now,
                    finished_at=now,
                ),
            )
        return [run_id]

    client, db_path, _settings = _client(tmp_path, bus, fake_runner)
    _seed(db_path)

    with client:
        response = client.post("/api/skills/skill_eval/evaluate", json={})
        assert response.status_code == 202
        body = response.json()
        assert body["job_id"].startswith("job_")
        job_id = body["job_id"]

        job_events = [e for e in collected if e.run_id == job_id]
        assert [e.type for e in job_events] == [
            TraceEventType.WORKFLOW_STARTED,
            TraceEventType.EVALUATION_COMPLETED,
        ]
        assert job_events[0].name == "evaluate"
        assert job_events[0].stage == "evaluator"
        assert job_events[1].output["status"] == "completed"
        assert job_events[1].output["run_ids"] == ["eval_run_1"]

        get_resp = client.get("/api/skills/skill_eval/evaluations/eval_run_1")
        assert get_resp.status_code == 200
        run_body = get_resp.json()
        assert run_body["id"] == "eval_run_1"
        assert run_body["skill_version_id"] == "ver_eval"
        assert run_body["metrics"] == {"passed": True, "latency_ms": 12}
        assert run_body["status"] == "completed"


def test_unknown_skill_does_not_call_runner(tmp_path: Path) -> None:
    bus = EventBus()
    called: list[str] = []

    async def fake_runner(**_kwargs) -> list[str]:
        called.append("ran")
        return []

    client, _db, _settings = _client(tmp_path, bus, fake_runner)
    with client:
        response = client.post("/api/skills/skill_missing/evaluate", json={"repeats": 1})
    assert response.status_code == 404
    assert called == []


def test_get_evaluation_for_other_skill_is_404(tmp_path: Path) -> None:
    bus = EventBus()

    async def fake_runner(**_kwargs) -> list[str]:
        return []

    client, db_path, _settings = _client(tmp_path, bus, fake_runner)
    now = datetime.now(UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id="proj_a", name="a", created_at=now))
        insert_project(conn, Project(id="proj_b", name="b", created_at=now))
        insert_skill(
            conn,
            Skill(
                id="skill_a",
                project_id="proj_a",
                name="a",
                current_version_id="ver_a",
            ),
        )
        insert_skill(
            conn,
            Skill(
                id="skill_b",
                project_id="proj_b",
                name="b",
                current_version_id="ver_b",
            ),
        )
        insert_skill_version(
            conn,
            SkillVersion(
                id="ver_a",
                skill_id="skill_a",
                version="0.1",
                status=SkillVersionStatus.DRAFT,
                artifact_path="skills/a",
                created_at=now,
            ),
        )
        insert_skill_version(
            conn,
            SkillVersion(
                id="ver_b",
                skill_id="skill_b",
                version="0.1",
                status=SkillVersionStatus.DRAFT,
                artifact_path="skills/b",
                created_at=now,
            ),
        )
        insert_evaluation_run(
            conn,
            EvaluationRun(
                id="eval_owned_by_a",
                skill_version_id="ver_a",
                baseline={},
                metrics={"passed": True},
                status=EvaluationRunStatus.COMPLETED,
                started_at=now,
                finished_at=now,
            ),
        )

    with client:
        response = client.get("/api/skills/skill_b/evaluations/eval_owned_by_a")
    assert response.status_code == 404


def test_repeats_zero_is_422(tmp_path: Path) -> None:
    bus = EventBus()

    async def fake_runner(**_kwargs) -> list[str]:
        return []

    client, db_path, _settings = _client(tmp_path, bus, fake_runner)
    _seed(db_path)
    with client:
        response = client.post("/api/skills/skill_eval/evaluate", json={"repeats": 0})
    assert response.status_code == 422
