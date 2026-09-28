"""C7.1: FailureAnalyzer classifies failures; evidence must be verbatim."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from skillforge.config import Settings
from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import FailureClass, TraceEventType
from skillforge.evaluator.assertions import AssertionResult, FieldMismatch
from skillforge.evolution.analyzer import FailureAnalyzer
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.tracing.bus import EventBus

_RUN_ID = "run_f3_001"
_EMERG = 'nginx: [emerg] unknown directive "this_is_not_valid_nginx" in /etc/nginx/nginx.conf:12'
_VERIFIER = {
    "http_status": 502,
    "backend_running": True,
    "nginx_running": True,
    "health_ok": False,
    "db_reachable": True,
}


def _event(
    event_type: TraceEventType,
    *,
    name: str | None = None,
    input: dict | None = None,
    output: dict | None = None,
) -> TraceEvent:
    return TraceEvent(
        id=f"evt_{event_type.value}_{name or 'x'}",
        run_id=_RUN_ID,
        type=event_type,
        timestamp=datetime.now(UTC),
        stage="runtime",
        name=name,
        input=input or {},
        output=output or {},
    )


def _f3_events() -> list[TraceEvent]:
    return [
        _event(
            TraceEventType.TOOL_CALL,
            name="docker.restart",
            input={"service": "backend"},
        ),
        _event(
            TraceEventType.TOOL_RESULT,
            name="docker.restart",
            output={"ok": True, "service": "backend"},
        ),
        _event(
            TraceEventType.TOOL_CALL,
            name="nginx.reload",
            input={},
        ),
        _event(
            TraceEventType.TOOL_RESULT,
            name="nginx.reload",
            output={"ok": False, "stderr": _EMERG},
        ),
        _event(
            TraceEventType.TOOL_CALL,
            name="http.get",
            input={"url": "http://localhost:8088/health"},
        ),
        _event(
            TraceEventType.TOOL_RESULT,
            name="http.get",
            output={"status": 502, "body": "Bad Gateway"},
        ),
    ]


def _f3_assertion() -> AssertionResult:
    return AssertionResult(
        passed=False,
        mismatches=[
            FieldMismatch(field="http_status", expected=200, actual=502),
            FieldMismatch(field="health_ok", expected=True, actual=False),
        ],
        forbidden_hits=[],
    )


def _gateway(payload: dict) -> ModelGateway:
    return ModelGateway(
        FakeModelAdapter([ModelResponse(content=json.dumps(payload))]),
        settings=Settings(_env_file=None),
        bus=EventBus(),
    )


async def test_f3_failure_classified_missing_instruction() -> None:
    events = _f3_events()
    draft = {
        "class": "missing_instruction",
        "symptom": "agent restarted backend but nginx reload failed on invalid directive",
        "failed_assertion": "http_status expected 200 got 502",
        "evidence": [
            _EMERG,
            "Bad Gateway",
        ],
        "suspected_skill_gap": "No instruction to run nginx -t or remove this_is_not_valid_nginx",
    }
    analyzer = FailureAnalyzer(_gateway(draft), settings=Settings(_env_file=None))
    failure = await analyzer.analyze(
        run_id=_RUN_ID,
        events=events,
        assertion=_f3_assertion(),
        verifier=_VERIFIER,
    )
    assert failure.run_id == _RUN_ID
    assert failure.failure_class == FailureClass.MISSING_INSTRUCTION
    assert failure.evidence == [_EMERG, "Bad Gateway"]
    assert failure.source_support == []
    assert failure.suspected_skill_gap is not None
    assert "nginx -t" in failure.suspected_skill_gap


async def test_invented_evidence_is_dropped() -> None:
    events = _f3_events()
    draft = {
        "class": "missing_instruction",
        "symptom": "reload failed",
        "failed_assertion": "health_ok still false",
        "evidence": [
            _EMERG,
            "agent forgot to run nginx -t before reload",
            "invented paraphrase of upstream mismatch",
        ],
        "suspected_skill_gap": "Missing diagnostic step for invalid nginx directives",
    }
    analyzer = FailureAnalyzer(_gateway(draft), settings=Settings(_env_file=None))
    failure = await analyzer.analyze(
        run_id=_RUN_ID,
        events=events,
        assertion=_f3_assertion(),
        verifier=_VERIFIER,
    )
    assert failure.evidence == [_EMERG]
    assert all("invented" not in item for item in failure.evidence)
    assert all("forgot" not in item for item in failure.evidence)
    assert failure.source_support == []
