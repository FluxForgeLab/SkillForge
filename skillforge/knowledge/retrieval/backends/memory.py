"""In-memory keyword index for tests. It does not read SQLite."""

from __future__ import annotations

from collections.abc import Sequence

from skillforge.knowledge.retrieval.base import (
    IndexDocument,
    RetrievalHit,
    RetrievalMode,
    RetrievalQuery,
)


class MemoryIndex:
    """Case-insensitive token overlap. Unsupported modes degrade to keyword."""

    name = "memory"
    capabilities: frozenset[RetrievalMode] = frozenset({"keyword"})

    def __init__(self) -> None:
        self._docs: dict[str, IndexDocument] = {}

    async def ensure_schema(self) -> None:
        return None

    async def upsert(self, docs: Sequence[IndexDocument]) -> None:
        for doc in docs:
            self._docs[doc.id] = doc

    async def delete(self, *, project_id: str, document_id: str | None = None) -> None:
        kept: dict[str, IndexDocument] = {}
        for doc_id, doc in self._docs.items():
            other_project = doc.project_id != project_id
            other_document = document_id is not None and doc.document_id != document_id
            if other_project or other_document:
                kept[doc_id] = doc
        self._docs = kept

    async def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        mode_used: RetrievalMode = query.mode if query.mode in self.capabilities else "keyword"
        tokens = [token for token in query.text.lower().split() if token]
        if not tokens:
            return []
        hits: list[RetrievalHit] = []
        for doc in self._docs.values():
            if not _matches(doc, query):
                continue
            haystack = f"{doc.title or ''} {doc.text}".lower()
            matched = sum(1 for token in tokens if token in haystack)
            if matched == 0:
                continue
            hits.append(
                RetrievalHit(
                    id=doc.id,
                    kind=doc.kind,
                    score=matched / len(tokens),
                    text=doc.text,
                    title=doc.title,
                    type=doc.type,
                    document_id=doc.document_id,
                    page=doc.page,
                    line_start=doc.line_start,
                    backend=self.name,
                    mode_used=mode_used,
                )
            )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[: query.k]


def _matches(doc: IndexDocument, query: RetrievalQuery) -> bool:
    if doc.project_id != query.project_id:
        return False
    if doc.kind not in query.kinds:
        return False
    if query.type is not None and (doc.kind != "knowledge_unit" or doc.type != query.type):
        return False
    if query.document_ids is not None and doc.document_id not in query.document_ids:
        return False
    return True
