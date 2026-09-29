"""C6.3: instruction ids and the source map are assigned in code."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from skillforge.compiler import SkillMarkdown, render_skill_markdown
from skillforge.compiler.skill_md import source_map_json
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.knowledge_units import insert_knowledge_unit
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.source_documents import insert_source_document
from skillforge.domain.entities import KnowledgeUnit, Project, SkillSpec, SourceDocument
from skillforge.domain.enums import KnowledgeUnitType
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.runtime.prompt import system_prompt
from skillforge.tracing.bus import EventBus

_DOCUMENT = "doc_runbook"
_SHA = "abc123"
_SELECTED = ["ku_down", "ku_proxy"]


async def test_unselected_citation_is_dropped_and_ids_are_assigned(tmp_path: Path) -> None:
    db_path = _seed(tmp_path)
    settings = Settings(_env_file=None, sqlite_path=db_path, data_dir=tmp_path / "data")
    rendered = await render_skill_markdown(
        db_path,
        _spec(),
        _SELECTED,
        _gateway(settings),
        settings=settings,
    )

    assert "nginx -t" not in rendered.skill_md
    assert "this_is_not_valid_nginx" not in rendered.skill_md
    assert "Inspect the backend." not in rendered.skill_md
    assert "ins_01 docker.inspect backend." in rendered.skill_md
    assert "ins_02 If stopped, docker.restart backend." in rendered.skill_md
    upstream = "ins_03 If the upstream line is not `server backend:8080;`, replace it."
    assert upstream in rendered.skill_md
    assert "ins_20 Do not restart mock-db." in rendered.skill_md
    assert list(rendered.source_map) == ["ins_01", "ins_02", "ins_03", "ins_20"]
    assert rendered.source_map["ins_01"]["knowledge_unit_id"] == "ku_down"
    assert rendered.source_map["ins_01"]["document"] == "runbook.md"
    assert rendered.source_map["ins_01"]["sha256"] == _SHA
    assert rendered.source_map["ins_01"]["line_start"] == 4
    assert "ku_appendix" not in json.dumps(rendered.source_map)
    _assert_prompt_reads_frontmatter(tmp_path, rendered)


def _assert_prompt_reads_frontmatter(tmp_path: Path, rendered: SkillMarkdown) -> None:
    root = tmp_path / "skill"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text(rendered.skill_md, encoding="utf-8")
    (root / "references" / "source-map.json").write_text(
        source_map_json(rendered.source_map),
        encoding="utf-8",
    )
    prompt = system_prompt(str(root))
    assert "name: service-recovery" in prompt
    assert "description: Diagnose and recover the edge service." in prompt
    assert "triggers: HTTP 502, backend unavailable, health check failed" in prompt
    assert "document=runbook.md" in prompt
    assert f"sha256={_SHA}" in prompt


def _gateway(settings: Settings) -> ModelGateway:
    payload = {
        "instructions": [
            {
                "knowledge_unit_id": "ku_down",
                "text": "Inspect the backend.",
                "kind": "procedure",
            },
            {
                "knowledge_unit_id": "ku_proxy",
                "text": "Read the upstream line.",
                "kind": "procedure",
            },
            {
                "knowledge_unit_id": "ku_down",
                "text": "Do not restart mock-db.",
                "kind": "prohibition",
            },
            {
                "knowledge_unit_id": "ku_appendix",
                "text": "Run nginx -t and remove this_is_not_valid_nginx.",
                "kind": "procedure",
            },
        ],
    }
    adapter = FakeModelAdapter([ModelResponse(content=json.dumps(payload))])
    return ModelGateway(adapter, settings=settings, sink=_Sink(), bus=EventBus())


class _Sink:
    async def write(self, event: object) -> None:
        del event


def _spec() -> SkillSpec:
    return SkillSpec(
        name="service-recovery",
        description="Diagnose and recover the edge service.",
        triggers=["HTTP 502", "backend unavailable", "health check failed"],
        tools=["docker.inspect", "http.get"],
        permissions={
            "filesystem": {"read": ["/workspace"], "write": ["/workspace/runtime"]},
            "network": {"allow": ["localhost"]},
            "shell": {"destructive_commands": False},
        },
        success=["HTTP 200 from the health check."],
        sources=[_DOCUMENT],
    )


def _seed(tmp_path: Path) -> Path:
    db_path = tmp_path / "app.sqlite"
    initialize_database(db_path)
    created = datetime(2026, 1, 1, tzinfo=UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id="proj_md", name="lab", created_at=created))
        insert_source_document(
            conn,
            SourceDocument(
                id=_DOCUMENT,
                project_id="proj_md",
                filename="runbook.md",
                sha256=_SHA,
                version="1",
                parser="markdown",
                created_at=created,
            ),
        )
        for unit in (
            _unit(
                "ku_down",
                "Service Down",
                steps=[
                    "docker.inspect backend.",
                    "If stopped, docker.restart backend.",
                ],
            ),
            _unit(
                "ku_proxy",
                "502 from proxy",
                steps=["If the upstream line is not `server backend:8080;`, replace it."],
            ),
        ):
            insert_knowledge_unit(conn, unit)
        insert_knowledge_unit(
            conn,
            _unit("ku_appendix", "Appendix B", steps=["Run nginx -t."]),
        )
    return db_path


def _unit(unit_id: str, title: str, steps: list[str] | None = None) -> KnowledgeUnit:
    return KnowledgeUnit(
        id=unit_id,
        document_id=_DOCUMENT,
        type=KnowledgeUnitType.PROCEDURE,
        content={
            "title": title,
            "trigger": title,
            "steps": steps or ["Look."],
            "source_refs": [
                {
                    "document_id": _DOCUMENT,
                    "chunk_id": f"chunk_{unit_id}",
                    "page": None,
                    "line_start": 4,
                    "line_end": 8,
                },
            ],
        },
    )
