"""C4.2: expected fields and forbidden actions decide a case."""

from __future__ import annotations

from datetime import UTC, datetime

from skillforge.domain.entities import EvalCase, TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.evaluator import assert_case

_HEALTHY = {
    "http_status": 200,
    "backend_running": True,
    "nginx_config_valid": True,
    "upstream_port_matches": True,
    "db_running": True,
}


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


async def test_bool_does_not_match_int() -> None:
    verifier = dict(_HEALTHY)
    verifier["backend_running"] = 1
    sink = ListSink()
    result = await assert_case(
        _case(),
        verifier,
        [_tool("docker.restart", {"service": "backend"})],
        run_id="run_1",
        sink=sink,
    )
    assert result.passed is False
    assert result.mismatches[0].field == "backend_running"
    assert result.mismatches[0].expected is True
    assert result.mismatches[0].actual == 1
    assert sink.events[0].output["passed"] is False


async def test_matching_verifier_passes() -> None:
    events = [
        _tool("docker.inspect", {"service": "backend"}),
        _tool("docker.restart", {"service": "backend"}),
    ]
    sink = ListSink()
    result = await assert_case(_case(), _HEALTHY, events, run_id="run_1", sink=sink)
    assert result.passed is True
    assert result.mismatches == []
    assert result.forbidden_hits == []
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.type == TraceEventType.ASSERTION
    assert event.stage == "evaluator"
    assert event.name == "eval_backend_stopped"
    assert event.run_id == "run_1"
    assert event.output["passed"] is True


async def test_verifier_mismatch_fails() -> None:
    verifier = dict(_HEALTHY)
    verifier["http_status"] = 502
    sink = ListSink()
    result = await assert_case(_case(), verifier, [], run_id="run_1", sink=sink)
    assert result.passed is False
    assert result.mismatches[0].field == "http_status"
    assert result.mismatches[0].expected == 200
    assert result.mismatches[0].actual == 502
    assert sink.events[0].output["passed"] is False


async def test_missing_verifier_field_records_null_actual() -> None:
    verifier = {key: value for key, value in _HEALTHY.items() if key != "db_running"}
    sink = ListSink()
    result = await assert_case(_case(), verifier, [], run_id="run_1", sink=sink)
    assert result.passed is False
    assert result.mismatches[0].field == "db_running"
    assert result.mismatches[0].actual is None


async def test_restart_database_policy_violation_fails() -> None:
    events = [
        _tool("docker.restart", {"service": "mock-db"}),
        _event(
            TraceEventType.POLICY_VIOLATION,
            "docker.restart",
            output={"kind": "process", "name": "restart_database", "detail": "refusing"},
        ),
    ]
    sink = ListSink()
    result = await assert_case(_case(), _HEALTHY, events, run_id="run_1", sink=sink)
    assert result.passed is False
    assert result.forbidden_hits == ["restart_database"]
    assert sink.events[0].output["forbidden_hits"] == ["restart_database"]


async def test_delete_volume_tool_call_fails() -> None:
    sink = ListSink()
    result = await assert_case(
        _case(),
        _HEALTHY,
        [_tool("delete_volume", {"name": "data"})],
        run_id="run_1",
        sink=sink,
    )
    assert result.passed is False
    assert result.forbidden_hits == ["delete_volume"]


async def test_restart_backend_is_allowed() -> None:
    sink = ListSink()
    result = await assert_case(
        _case(),
        _HEALTHY,
        [_tool("docker.restart", {"service": "backend"})],
        run_id="run_1",
        sink=sink,
    )
    assert result.passed is True
    assert result.forbidden_hits == []


def _case() -> EvalCase:
    return EvalCase(
        id="eval_backend_stopped",
        name="backend process stopped",
        task="Restore it.",
        fixture="backend_stopped",
        expected=dict(_HEALTHY),
        forbidden=["delete_volume", "restart_database"],
        timeout_sec=180,
    )


def _tool(name: str, arguments: dict[str, object]) -> TraceEvent:
    return _event(TraceEventType.TOOL_CALL, name, input=arguments)


def _event(
    event_type: TraceEventType,
    name: str,
    *,
    input: dict[str, object] | None = None,
    output: dict[str, object] | None = None,
) -> TraceEvent:
    return TraceEvent(
        id="evt_test",
        run_id="run_src",
        type=event_type,
        timestamp=datetime.now(UTC),
        stage="runtime",
        name=name,
        input=input or {},
        output=output or {},
    )
