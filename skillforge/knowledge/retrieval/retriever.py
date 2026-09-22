"""Facade. Callers search here and never construct an index backend."""

from __future__ import annotations

from skillforge.config import Settings
from skillforge.domain.enums import TraceEventType
from skillforge.knowledge.retrieval.base import (
    IndexKind,
    RetrievalHit,
    RetrievalIndex,
    RetrievalMode,
    RetrievalQuery,
)
from skillforge.knowledge.retrieval.embedder import Embedder
from skillforge.tracing.bus import EventBus
from skillforge.tracing.emitter import emit
from skillforge.tracing.sink import TraceSink


class Retriever:
    """Search one project. Keyword mode does not call the embedder."""

    def __init__(
        self,
        *,
        index: RetrievalIndex,
        embedder: Embedder,
        settings: Settings,
        sink: TraceSink | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._index = index
        self._embedder = embedder
        self._settings = settings
        self._sink = sink
        self._bus = bus if bus is not None else EventBus()

    async def search(
        self,
        text: str,
        project_id: str,
        *,
        kinds: tuple[IndexKind, ...] = ("chunk", "knowledge_unit"),
        type: str | None = None,
        document_ids: tuple[str, ...] | None = None,
        k: int = 10,
        mode: RetrievalMode | None = None,
        run_id: str = "retrieval",
    ) -> list[RetrievalHit]:
        chosen = mode if mode is not None else self._settings.retrieval_default_mode
        query = RetrievalQuery(
            text=text,
            project_id=project_id,
            kinds=kinds,
            type=type,
            document_ids=document_ids,
            k=k,
            mode=chosen,
        )
        hits = await self._index.search(query)
        mode_used = hits[0].mode_used if hits else _fallback_mode(chosen, self._index.capabilities)
        await emit(
            run_id,
            TraceEventType.RETRIEVAL_QUERY,
            name=self._index.name,
            output={
                "backend": self._index.name,
                "mode_used": mode_used,
                "k": k,
                "query_len": len(text),
                "hit_ids": [hit.id for hit in hits],
            },
            stage="knowledge",
            sink=self._sink,
            bus=self._bus,
        )
        return hits


def _fallback_mode(
    requested: RetrievalMode,
    capabilities: frozenset[RetrievalMode],
) -> RetrievalMode:
    if requested in capabilities:
        return requested
    if "keyword" in capabilities:
        return "keyword"
    return requested
