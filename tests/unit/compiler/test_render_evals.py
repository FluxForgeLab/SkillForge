"""C6.5: eval cases keep catalog fixtures and the recovered verifier oracle."""

from __future__ import annotations

import json
from pathlib import Path

from skillforge.compiler import render_evals
from skillforge.config import Settings
from skillforge.domain.entities import KnowledgeUnit
from skillforge.domain.enums import KnowledgeUnitType
from skillforge.evaluator.cases import load_eval_cases
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelRequest, ModelResponse
from skillforge.tracing.bus import EventBus


class _Remember:
    def __init__(self, inner: FakeModelAdapter) -> None:
        self._inner = inner
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return await self._inner.generate(request)


class _Sink:
    async def write(self, event: object) -> None:
        del event


async def test_unknown_fixture_dropped_and_expected_is_recovered(tmp_path: Path) -> None:
    remembered = _Remember(FakeModelAdapter([_draft()]))
    settings = Settings(
        _env_file=None, sqlite_path=tmp_path / "app.sqlite", data_dir=tmp_path / "data"
    )
    rendered = await render_evals(
        [_unit("HTTP 200 from the health check.")],
        _gateway(remembered, settings),
        settings=settings,
    )
    blob = "\n".join(
        message.content or "" for request in remembered.requests for message in request.messages
    )
    assert "nginx -t" not in blob
    assert "HTTP 200 from the health check." in blob

    skill = tmp_path / "skill"
    (skill / "evals").mkdir(parents=True)
    (skill / "evals" / "evals.json").write_text(rendered.evals_json, encoding="utf-8")
    loaded = load_eval_cases(skill)
    fixtures = [item.case.fixture for item in loaded]
    assert fixtures == [
        "backend_stopped",
        "nginx_wrong_upstream",
        "nginx_bad_config_reload",
    ]
    assert "not_a_fault" not in fixtures
    for item in loaded:
        assert item.fault_id == item.case.fixture
        assert item.case.expected["http_status"] == 200
        assert item.case.forbidden == ["delete_volume", "restart_database"]
        assert item.case.timeout_sec == 180


def _draft() -> ModelResponse:
    payload = {
        "cases": [
            _case("eval_backend_stopped", "backend_stopped"),
            _case("eval_nginx_wrong_upstream", "nginx_wrong_upstream"),
            _case("eval_missing", "not_a_fault"),
            _case("eval_nginx_bad_config_reload", "nginx_bad_config_reload"),
        ],
    }
    return ModelResponse(content=json.dumps(payload))


def _case(case_id: str, fixture: str) -> dict[str, object]:
    return {
        "id": case_id,
        "name": fixture,
        "task": "Restore the service.",
        "fixture": fixture,
        "expected": {"http_status": 502},
        "forbidden": [],
    }


def _unit(criterion: str) -> KnowledgeUnit:
    return KnowledgeUnit(
        id="ku_down",
        document_id="doc_runbook",
        type=KnowledgeUnitType.PROCEDURE,
        content={"title": "Service Down", "success_criteria": [criterion]},
    )


def _gateway(adapter: _Remember, settings: Settings) -> ModelGateway:
    return ModelGateway(adapter, settings=settings, sink=_Sink(), bus=EventBus())
