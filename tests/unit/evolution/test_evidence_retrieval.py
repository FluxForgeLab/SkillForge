"""C7.2: Failure evidence retrieval fills source_support via Retriever."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from skillforge.config import Settings
from skillforge.domain.entities import Failure, TraceEvent
from skillforge.domain.enums import FailureClass, TraceEventType
from skillforge.evaluator.assertions import AssertionResult, FieldMismatch
from skillforge.evolution.analyzer import FailureAnalyzer
from skillforge.evolution.evidence import enrich_source_support, format_source_ref, query_text
from skillforge.knowledge.retrieval.backends.memory import MemoryIndex
from skillforge.knowledge.retrieval.base import IndexDocument, RetrievalHit
from skillforge.knowledge.retrieval.embedder import NullEmbedder
from skillforge.knowledge.retrieval.retriever import Retriever
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.tracing.bus import EventBus

_RUNBOOK_INDEX = (
    Path(__file__).resolve().parents[2] / "fixtures" / "retrieval" / "runbook_index.json"
)
_FIXED_QUERY = "502 upstream nginx -t"
_PROJECT_ID = "proj_runbook"
_APPENDIX_LINE = 31
_RUN_ID = "run_f3_001"
_EMERG = 'nginx: [emerg] unknown directive "this_is_not_valid_nginx" in /etc/nginx/nginx.conf:12'
_VERIFIER = {
    "http_status": 502,
    "backend_running": True,
    "nginx_running": True,
    "health_ok": False,
    "db_reachable": True,
}


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        retrieval_backend="memory",
        retrieval_default_mode="keyword",
    )


async def _memory_retriever() -> Retriever:
    rows = json.loads(_RUNBOOK_INDEX.read_text(encoding="utf-8"))
    index = MemoryIndex()
    await index.upsert([IndexDocument.model_validate(row) for row in rows])
    return Retriever(
        index=index,
        embedder=NullEmbedder(),
        settings=_settings(),
        bus=EventBus(),
    )


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
        _event(TraceEventType.TOOL_CALL, name="docker.restart", input={"service": "backend"}),
        _event(
            TraceEventType.TOOL_RESULT,
            name="docker.restart",
            output={"ok": True, "service": "backend"},
        ),
        _event(TraceEventType.TOOL_CALL, name="nginx.reload", input={}),
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
        settings=_settings(),
        bus=EventBus(),
    )


async def test_f3_fixed_query_recalls_appendix_b_into_source_support() -> None:
    retriever = await _memory_retriever()
    failure = Failure(
        run_id=_RUN_ID,
        failure_class=FailureClass.MISSING_INSTRUCTION,
        symptom=_FIXED_QUERY,
        failed_assertion=None,
        evidence=[_EMERG],
        suspected_skill_gap="Missing nginx -t before reload",
        source_support=[],
    )
    assert query_text(failure) == _FIXED_QUERY
    hits = await retriever.search(_FIXED_QUERY, _PROJECT_ID, k=3)
    assert any(hit.title is not None and "Appendix B" in hit.title for hit in hits)

    enriched = await enrich_source_support(failure, retriever, _PROJECT_ID, k=3)
    assert enriched.source_support
    assert f"doc_runbook#page={_APPENDIX_LINE}" in enriched.source_support
    assert all("#page" in ref for ref in enriched.source_support)
    assert enriched.evidence == failure.evidence


async def test_analyzer_fills_source_support_when_retriever_present() -> None:
    retriever = await _memory_retriever()
    draft = {
        "class": "missing_instruction",
        "symptom": _FIXED_QUERY,
        "failed_assertion": None,
        "evidence": [_EMERG, "Bad Gateway"],
        "suspected_skill_gap": "No instruction to run nginx -t",
    }
    analyzer = FailureAnalyzer(
        _gateway(draft),
        settings=_settings(),
        retriever=retriever,
        project_id=_PROJECT_ID,
    )
    failure = await analyzer.analyze(
        run_id=_RUN_ID,
        events=_f3_events(),
        assertion=_f3_assertion(),
        verifier=_VERIFIER,
    )
    assert failure.failure_class == FailureClass.MISSING_INSTRUCTION
    assert failure.evidence == [_EMERG, "Bad Gateway"]
    assert f"doc_runbook#page={_APPENDIX_LINE}" in failure.source_support


async def test_format_source_ref_prefers_page_over_line() -> None:
    hit = RetrievalHit(
        id="h1",
        kind="chunk",
        score=1.0,
        text="body",
        title="Appendix B",
        document_id="doc_x",
        page=2,
        line_start=31,
        backend="memory",
        mode_used="keyword",
    )
    assert format_source_ref(hit) == "doc_x#page=2"
