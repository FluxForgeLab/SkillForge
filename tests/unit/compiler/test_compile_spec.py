"""C6.2: scope triggers select knowledge units; the rule layer only tightens grants."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from skillforge.compiler import TaskScope, compile_skill_spec
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.knowledge_units import insert_knowledge_unit
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.source_documents import insert_source_document
from skillforge.domain.entities import KnowledgeUnit, Project, SourceDocument
from skillforge.domain.enums import KnowledgeUnitType
from skillforge.knowledge.retrieval.backends.memory import MemoryIndex
from skillforge.knowledge.retrieval.embedder import NullEmbedder
from skillforge.knowledge.retrieval.indexer import Indexer
from skillforge.knowledge.retrieval.retriever import Retriever
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelRequest, ModelResponse
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import TraceSink

_SCOPE = ["HTTP 502", "backend unavailable", "health check failed"]
_APPENDIX = "nginx reload failed / upstream mismatch"
_PROJECT = "proj_compile"
_DOCUMENT = "doc_runbook"


class _Remember:
    def __init__(self, inner: FakeModelAdapter) -> None:
        self._inner = inner
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return await self._inner.generate(request)


class _Sink:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def write(self, event: object) -> None:
        self.events.append(event)


async def test_scope_excludes_appendix_b_and_tightens_permissions(tmp_path: Path) -> None:
    db_path, settings, retriever = await _world(tmp_path, _units())
    hits = await retriever.search(" ".join(_SCOPE), _PROJECT, kinds=("knowledge_unit",))
    assert "ku_03_appendix" in {hit.id for hit in hits}

    remembered = _Remember(FakeModelAdapter([_draft()]))
    compiled = await compile_skill_spec(
        db_path,
        _PROJECT,
        _scope(),
        _gateway(remembered, settings),
        retriever=retriever,
        settings=settings,
    )

    assert compiled.selected_unit_ids == ["ku_01_down", "ku_02_proxy"]
    parts = [
        message.content or "" for request in remembered.requests for message in request.messages
    ]
    blob = "\n".join(parts)
    assert "nginx -t" not in blob
    assert "this_is_not_valid_nginx" not in blob
    assert "backend unavailable" in blob
    spec = compiled.spec
    assert spec.triggers == _SCOPE
    assert spec.tools == ["docker.inspect"]
    assert spec.permissions.filesystem.write == ["/workspace/runtime"]
    assert spec.permissions.network.allow == ["localhost"]
    assert spec.permissions.shell.destructive_commands is False
    assert spec.sources == [_DOCUMENT]


async def test_matching_diagnostic_rule_stays_selected(tmp_path: Path) -> None:
    units = _units() + [
        _unit(
            "ku_04_health",
            KnowledgeUnitType.DIAGNOSTIC_RULE,
            "Health check failed",
            "health check failed",
            ["Read the health endpoint."],
        ),
    ]
    db_path, settings, retriever = await _world(tmp_path, units)
    compiled = await compile_skill_spec(
        db_path,
        _PROJECT,
        _scope(),
        _gateway(_Remember(FakeModelAdapter([_draft()])), settings),
        retriever=retriever,
        settings=settings,
    )
    assert "ku_04_health" in compiled.selected_unit_ids
    assert "ku_03_appendix" not in compiled.selected_unit_ids


def _scope() -> TaskScope:
    return TaskScope(
        name="service-recovery",
        description="Diagnose and recover containerized web services.",
        triggers=list(_SCOPE),
    )


def _draft() -> ModelResponse:
    payload = {
        "name": "service-recovery",
        "description": "Diagnose and recover containerized web services.",
        "triggers": [_APPENDIX],
        "tools": ["docker.inspect", "rm", "docker.nuke"],
        "permissions": {
            "filesystem": {
                "read": ["/workspace"],
                "write": ["/workspace/config", "/workspace/runtime"],
            },
            "network": {"allow": ["localhost", "8.8.8.8"]},
            "shell": {"destructive_commands": True},
        },
        "success": ["health_status == 200"],
        "sources": ["doc_other"],
    }
    return ModelResponse(content=json.dumps(payload))


def _units() -> list[KnowledgeUnit]:
    return [
        _unit(
            "ku_01_down",
            KnowledgeUnitType.PROCEDURE,
            "Service Down",
            "backend unavailable",
            ["Inspect the backend service."],
        ),
        _unit(
            "ku_02_proxy",
            KnowledgeUnitType.PROCEDURE,
            "502 from proxy",
            "HTTP 502 from reverse proxy",
            ["Read the upstream line."],
        ),
        _unit(
            "ku_03_appendix",
            KnowledgeUnitType.DIAGNOSTIC_RULE,
            "Appendix B: Reverse Proxy Troubleshooting",
            _APPENDIX,
            [
                "Run nginx -t before any nginx reload.",
                "Compare the upstream port with the backend listen port.",
                "Remove this_is_not_valid_nginx;.",
            ],
        ),
    ]


def _unit(
    unit_id: str,
    unit_type: KnowledgeUnitType,
    title: str,
    trigger: str,
    steps: list[str],
) -> KnowledgeUnit:
    return KnowledgeUnit(
        id=unit_id,
        document_id=_DOCUMENT,
        type=unit_type,
        content={
            "title": title,
            "trigger": trigger,
            "steps": steps,
            "success_criteria": [],
            "safety_constraints": [],
            "text": "\n".join([title, trigger, *steps]),
        },
    )


async def _world(
    tmp_path: Path,
    units: list[KnowledgeUnit],
) -> tuple[Path, Settings, Retriever]:
    db_path = tmp_path / "app.sqlite"
    settings = Settings(
        _env_file=None,
        sqlite_path=db_path,
        data_dir=tmp_path / "data",
        retrieval_backend="memory",
    )
    initialize_database(db_path)
    created = datetime(2026, 1, 1, tzinfo=UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id=_PROJECT, name="lab", created_at=created))
        insert_source_document(
            conn,
            SourceDocument(
                id=_DOCUMENT,
                project_id=_PROJECT,
                filename="runbook.md",
                sha256="abc",
                version="1",
                parser="markdown",
                created_at=created,
            ),
        )
        for unit in units:
            insert_knowledge_unit(conn, unit)
    index = MemoryIndex()
    await Indexer(db_path, index).index_knowledge_units(_DOCUMENT)
    sink: TraceSink = _Sink()
    retriever = Retriever(
        index=index,
        embedder=NullEmbedder(),
        settings=settings,
        sink=sink,
        bus=EventBus(),
    )
    return db_path, settings, retriever


def _gateway(adapter: _Remember, settings: Settings) -> ModelGateway:
    return ModelGateway(adapter, settings=settings, sink=_Sink(), bus=EventBus())
