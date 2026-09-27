"""C6.9: a replayed compile matches the golden acceptance checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from skillforge.compiler.evals import render_evals
from skillforge.compiler.passes import TaskScope, compile_skill_spec
from skillforge.compiler.scripts import render_scripts
from skillforge.compiler.skill_md import render_skill_markdown, source_map_json
from skillforge.compiler.validate import validate_skill_dir
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.knowledge_units import (
    insert_knowledge_unit,
    list_knowledge_units_by_project,
)
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.source_documents import insert_source_document
from skillforge.domain.entities import KnowledgeUnit, Project, SourceDocument
from skillforge.domain.enums import KnowledgeUnitType
from skillforge.knowledge.retrieval.embedder import NullEmbedder
from skillforge.knowledge.retrieval.factory import build_index
from skillforge.knowledge.retrieval.retriever import Retriever
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import SqliteTraceSink

_REPO = Path(__file__).resolve().parents[3]
_FIXTURE = _REPO / "tests" / "fixtures" / "compiler" / "service-recovery-v0.1.json"
_PROJECT = "proj_accept"
_DOCUMENT = "doc_runbook"
_SCOPE = ["HTTP 502", "backend unavailable", "health check failed"]
_APPENDIX = "nginx reload failed / upstream mismatch"


async def test_compiled_skill_meets_golden_acceptance(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    settings = _settings(tmp_path, db_path)
    _seed(db_path)
    gateway = _gateway(settings)
    bus = EventBus()
    sink = SqliteTraceSink(db_path)
    retriever = Retriever(
        index=build_index(settings, db_path=db_path),
        embedder=NullEmbedder(),
        settings=settings,
        sink=sink,
        bus=bus,
    )
    compiled = await compile_skill_spec(
        db_path,
        _PROJECT,
        TaskScope(
            name="service-recovery",
            description="Diagnose and recover the edge service.",
            triggers=list(_SCOPE),
        ),
        gateway,
        retriever=retriever,
        settings=settings,
    )
    markdown = await render_skill_markdown(
        db_path,
        compiled.spec,
        compiled.selected_unit_ids,
        gateway,
        settings=settings,
    )
    scripts = await render_scripts(compiled.spec, gateway, settings=settings)
    with connection(db_path) as conn:
        units = list_knowledge_units_by_project(conn, _PROJECT)
    selected = [unit for unit in units if unit.id in compiled.selected_unit_ids]
    evals = await render_evals(selected, gateway, settings=settings)

    skill_dir = _write(
        tmp_path / "skill", markdown.skill_md, markdown.source_map, scripts.files, evals.evals_json
    )
    result = await validate_skill_dir(skill_dir, run_id="accept", sink=sink, bus=bus)
    assert result.passed, result.errors

    loaded = json.loads((skill_dir / "evals" / "evals.json").read_text(encoding="utf-8"))
    fixtures = {item["fixture"] for item in loaded}
    assert "backend_stopped" in fixtures
    assert "nginx_wrong_upstream" in fixtures

    body = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "nginx -t" not in body
    assert "this_is_not_valid_nginx" not in body
    assert _APPENDIX not in body


def _settings(tmp_path: Path, db_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        sqlite_path=db_path,
        data_dir=tmp_path / "data",
        retrieval_backend="memory",
    )


def _gateway(settings: Settings) -> ModelGateway:
    payloads = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    script = [ModelResponse(content=json.dumps(item)) for item in payloads]
    return ModelGateway(
        FakeModelAdapter(script),
        settings=settings,
        sink=SqliteTraceSink(settings.sqlite_path),
        bus=EventBus(),
    )


def _seed(db_path: Path) -> None:
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
                sha256="abc123",
                version="1",
                parser="markdown",
                created_at=created,
            ),
        )
        insert_knowledge_unit(
            conn, _unit("ku_down", "Service Down", "backend unavailable", ["Inspect the backend."])
        )
        insert_knowledge_unit(
            conn,
            _unit(
                "ku_proxy",
                "502 from proxy",
                "HTTP 502 from reverse proxy",
                ["Read the upstream line."],
            ),
        )
        insert_knowledge_unit(
            conn,
            _unit(
                "ku_appendix",
                "Appendix B: Reverse Proxy Troubleshooting",
                _APPENDIX,
                [
                    "Run nginx -t before any nginx reload.",
                    "Remove this_is_not_valid_nginx;.",
                ],
            ),
        )


def _unit(unit_id: str, title: str, trigger: str, steps: list[str]) -> KnowledgeUnit:
    return KnowledgeUnit(
        id=unit_id,
        document_id=_DOCUMENT,
        type=KnowledgeUnitType.PROCEDURE
        if unit_id != "ku_appendix"
        else KnowledgeUnitType.DIAGNOSTIC_RULE,
        content={
            "title": title,
            "trigger": trigger,
            "steps": steps,
            "success_criteria": ["HTTP 200 from the health check."],
            "source_refs": [
                {
                    "document_id": _DOCUMENT,
                    "chunk_id": f"chunk_{unit_id}",
                    "line_start": 4,
                    "line_end": 8,
                },
            ],
        },
    )


def _write(
    root: Path,
    skill_md: str,
    source_map: dict,
    scripts: dict[str, str],
    evals_json: str,
) -> Path:
    (root / "references").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "evals").mkdir()
    (root / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (root / "references" / "source-map.json").write_text(
        source_map_json(source_map), encoding="utf-8"
    )
    for name, source in scripts.items():
        (root / "scripts" / name).write_text(source, encoding="utf-8")
    (root / "evals" / "evals.json").write_text(evals_json, encoding="utf-8")
    return root
