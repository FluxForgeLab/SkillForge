"""Build the retrieval stack from Settings. Business code does not construct backends."""

from __future__ import annotations

from pathlib import Path

from skillforge.config import Settings
from skillforge.knowledge.retrieval.backends.memory import MemoryIndex
from skillforge.knowledge.retrieval.backends.sqlite_fts import SqliteFtsIndex
from skillforge.knowledge.retrieval.base import RetrievalIndex
from skillforge.knowledge.retrieval.embedder import Embedder, NullEmbedder
from skillforge.knowledge.retrieval.retriever import Retriever
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import TraceSink


def build_index(settings: Settings, *, db_path: Path | None = None) -> RetrievalIndex:
    """Return the configured index. ``db_path`` overrides ``settings.sqlite_path``."""
    if settings.retrieval_backend == "memory":
        return MemoryIndex()
    if settings.retrieval_backend == "sqlite_fts":
        return SqliteFtsIndex(db_path if db_path is not None else settings.sqlite_path)
    raise ValueError(f"retrieval backend {settings.retrieval_backend!r} is not available")


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedder == "null":
        return NullEmbedder()
    raise ValueError(f"embedder {settings.embedder!r} is not available")


def build_retriever(
    settings: Settings,
    *,
    sink: TraceSink | None = None,
    bus: EventBus | None = None,
) -> Retriever:
    return Retriever(
        index=build_index(settings),
        embedder=build_embedder(settings),
        settings=settings,
        sink=sink,
        bus=bus,
    )
