"""Retrieval port. Fields stay additive so later backends do not change callers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

IndexKind = Literal["chunk", "knowledge_unit"]
RetrievalMode = Literal["keyword", "vector", "hybrid"]


class IndexDocument(BaseModel):
    """One indexed row. The indexer builds it from SQLite; backends do not read SQLite."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: IndexKind
    project_id: str
    document_id: str
    text: str
    title: str | None = None
    type: str | None = None
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    vector: list[float] | None = None


class RetrievalQuery(BaseModel):
    """A search request. Callers do not fill ``vector``."""

    model_config = ConfigDict(extra="forbid")

    text: str
    project_id: str
    kinds: tuple[IndexKind, ...] = ("chunk", "knowledge_unit")
    type: str | None = None
    document_ids: tuple[str, ...] | None = None
    k: int = 10
    mode: RetrievalMode = "keyword"
    vector: list[float] | None = None


class RetrievalHit(BaseModel):
    """A ranked hit. ``score`` is in ``[0, 1]`` and is only for ordering."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: IndexKind
    score: float
    text: str
    title: str | None = None
    type: str | None = None
    document_id: str
    page: int | None = None
    line_start: int | None = None
    backend: str
    mode_used: RetrievalMode


class RetrievalIndex(Protocol):
    """A disposable projection. ``ensure_schema`` may create ``idx_*`` storage."""

    name: str
    capabilities: frozenset[RetrievalMode]

    async def ensure_schema(self) -> None: ...

    async def upsert(self, docs: Sequence[IndexDocument]) -> None: ...

    async def delete(self, *, project_id: str, document_id: str | None = None) -> None: ...

    async def search(self, query: RetrievalQuery) -> list[RetrievalHit]: ...
