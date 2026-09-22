"""Embedding port. The MVP implementation does not call a model."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """Turns text into vectors. Callers never construct a backend-specific embedder."""

    name: str
    dimension: int | None

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class NullEmbedder:
    """Placeholder. Keyword search does not call it."""

    name = "null"
    dimension = None

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        del texts
        raise NotImplementedError("NullEmbedder does not embed documents")

    async def embed_query(self, text: str) -> list[float]:
        del text
        raise NotImplementedError("NullEmbedder does not embed queries")
