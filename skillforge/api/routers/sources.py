"""Upload sources, list knowledge, search, and rebuild the project index."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict

from skillforge.api.deps import get_settings_dep
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.repositories.knowledge_units import list_knowledge_units_by_project
from skillforge.db.repositories.projects import get_project
from skillforge.db.repositories.source_documents import list_source_documents
from skillforge.domain.entities import KnowledgeUnit, SourceDocument
from skillforge.ingestion.chunking import chunk_document
from skillforge.ingestion.store import store_upload
from skillforge.ingestion.text import parse_stored
from skillforge.knowledge.extractor import extract_document
from skillforge.knowledge.retrieval.factory import build_embedder, build_index
from skillforge.knowledge.retrieval.indexer import Indexer
from skillforge.knowledge.retrieval.retriever import Retriever
from skillforge.models.adapters.base import ModelAdapter
from skillforge.models.gateway import ModelGateway, build_adapter
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import SqliteTraceSink

router = APIRouter(prefix="/projects", tags=["sources"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


class SourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    filename: str
    sha256: str
    version: str
    parser: str
    created_at: datetime


class KnowledgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    document_id: str
    type: str
    title: str
    confidence: float | None
    content: dict[str, Any]


class SearchHitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    score: float
    title: str | None
    text: str
    document_id: str


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: str
    mode_used: str
    hits: list[SearchHitResponse]


class RebuildResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    status: str


def get_gateway(request: Request, settings: SettingsDep) -> ModelGateway:
    adapter: ModelAdapter = build_adapter(settings)
    return ModelGateway(
        adapter,
        settings=settings,
        sink=SqliteTraceSink(settings.sqlite_path),
        bus=request.app.state.bus,
    )


GatewayDep = Annotated[ModelGateway, Depends(get_gateway)]


def _require_project(settings: Settings, project_id: str) -> None:
    with connection(settings.sqlite_path) as conn:
        if get_project(conn, project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")


def _source_response(document: SourceDocument) -> SourceResponse:
    return SourceResponse(
        id=document.id,
        project_id=document.project_id,
        filename=document.filename,
        sha256=document.sha256,
        version=document.version,
        parser=document.parser,
        created_at=document.created_at,
    )


def _knowledge_response(unit: KnowledgeUnit) -> KnowledgeResponse:
    title = unit.content.get("title")
    return KnowledgeResponse(
        id=unit.id,
        document_id=unit.document_id,
        type=unit.type.value,
        title=str(title) if title is not None else "",
        confidence=unit.confidence,
        content=unit.content,
    )


def _ingest(settings: Settings, project_id: str, filename: str, data: bytes) -> SourceDocument:
    root = settings.data_dir / "sources"
    document = store_upload(settings.sqlite_path, project_id, filename, data, root=root)
    parsed = parse_stored(document, root)
    chunk_document(settings.sqlite_path, document, parsed, settings=settings)
    return document


@router.post(
    "/{project_id}/sources",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source(
    project_id: str,
    file: UploadFile,
    settings: SettingsDep,
) -> SourceResponse:
    await asyncio.to_thread(_require_project, settings, project_id)
    data = await file.read()
    filename = file.filename or "upload.txt"
    document = await asyncio.to_thread(_ingest, settings, project_id, filename, data)
    return _source_response(document)


@router.get("/{project_id}/sources", response_model=list[SourceResponse])
async def list_sources(project_id: str, settings: SettingsDep) -> list[SourceResponse]:
    await asyncio.to_thread(_require_project, settings, project_id)

    def _list() -> list[SourceDocument]:
        with connection(settings.sqlite_path) as conn:
            return list_source_documents(conn, project_id)

    documents = await asyncio.to_thread(_list)
    return [_source_response(document) for document in documents]


@router.post("/{project_id}/extract", response_model=list[KnowledgeResponse])
async def extract_project(
    project_id: str,
    settings: SettingsDep,
    gateway: GatewayDep,
) -> list[KnowledgeResponse]:
    await asyncio.to_thread(_require_project, settings, project_id)

    def _documents() -> list[SourceDocument]:
        with connection(settings.sqlite_path) as conn:
            return list_source_documents(conn, project_id)

    documents = await asyncio.to_thread(_documents)
    index = build_index(settings, db_path=settings.sqlite_path)
    units: list[KnowledgeUnit] = []
    for document in documents:
        extracted = await extract_document(
            settings.sqlite_path,
            document.id,
            gateway,
            index=index,
        )
        units.extend(extracted)
    return [_knowledge_response(unit) for unit in units]


@router.get("/{project_id}/knowledge", response_model=list[KnowledgeResponse])
async def list_knowledge(project_id: str, settings: SettingsDep) -> list[KnowledgeResponse]:
    await asyncio.to_thread(_require_project, settings, project_id)

    def _list() -> list[KnowledgeUnit]:
        with connection(settings.sqlite_path) as conn:
            return list_knowledge_units_by_project(conn, project_id)

    units = await asyncio.to_thread(_list)
    return [_knowledge_response(unit) for unit in units]


@router.get("/{project_id}/knowledge/search", response_model=SearchResponse)
async def search_knowledge(
    project_id: str,
    settings: SettingsDep,
    request: Request,
    q: str = Query(min_length=1),
) -> SearchResponse:
    await asyncio.to_thread(_require_project, settings, project_id)
    index = build_index(settings, db_path=settings.sqlite_path)
    bus: EventBus = request.app.state.bus
    retriever = Retriever(
        index=index,
        embedder=build_embedder(settings),
        settings=settings,
        sink=SqliteTraceSink(settings.sqlite_path),
        bus=bus,
    )
    hits = await retriever.search(q, project_id, k=10)
    if hits:
        backend = hits[0].backend
        mode_used = hits[0].mode_used
    else:
        backend = index.name
        mode_used = settings.retrieval_default_mode
    return SearchResponse(
        backend=backend,
        mode_used=mode_used,
        hits=[
            SearchHitResponse(
                id=hit.id,
                kind=hit.kind,
                score=hit.score,
                title=hit.title,
                text=hit.text,
                document_id=hit.document_id,
            )
            for hit in hits
        ],
    )


@router.post("/{project_id}/index/rebuild", response_model=RebuildResponse)
async def rebuild_index(project_id: str, settings: SettingsDep) -> RebuildResponse:
    await asyncio.to_thread(_require_project, settings, project_id)
    index = build_index(settings, db_path=settings.sqlite_path)
    await Indexer(settings.sqlite_path, index).rebuild(project_id)
    return RebuildResponse(project_id=project_id, status="rebuilt")
