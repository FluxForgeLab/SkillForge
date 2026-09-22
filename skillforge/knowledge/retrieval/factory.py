"""Build the retrieval stack from Settings. Business code does not construct backends."""

from __future__ import annotations

from skillforge.config import Settings
from skillforge.knowledge.retrieval.backends.memory import MemoryIndex
from skillforge.knowledge.retrieval.base import RetrievalIndex
from skillforge.knowledge.retrieval.embedder import Embedder, NullEmbedder
from skillforge.knowledge.retrieval.retriever import Retriever
from skillforge.tracing.bus import EventBus
from skillforge.tracing.sink import TraceSink


def build_index(settings: Settings) -> RetrievalIndex:
    if settings.retrieval_backend == "memory":
        return MemoryIndex()
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
