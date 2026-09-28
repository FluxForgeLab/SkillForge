"""Retrieve document locators that support a Failure."""

from __future__ import annotations

from skillforge.domain.entities import Failure
from skillforge.knowledge.retrieval.base import RetrievalHit
from skillforge.knowledge.retrieval.retriever import Retriever

_DEFAULT_K = 3


def query_text(failure: Failure) -> str:
    """Build the keyword query from symptom and optional failed_assertion."""
    parts: list[str] = []
    symptom = failure.symptom.strip()
    if symptom:
        parts.append(symptom)
    if failure.failed_assertion is not None:
        assertion = failure.failed_assertion.strip()
        if assertion:
            parts.append(assertion)
    return " ".join(parts)


def format_source_ref(hit: RetrievalHit) -> str:
    """Format a hit as ``doc#page=N`` (page, else Markdown line_start)."""
    loc = hit.page if hit.page is not None else hit.line_start
    if loc is not None:
        return f"{hit.document_id}#page={loc}"
    return f"{hit.document_id}#page"


async def enrich_source_support(
    failure: Failure,
    retriever: Retriever,
    project_id: str,
    *,
    k: int = _DEFAULT_K,
    run_id: str | None = None,
) -> Failure:
    """Fill ``source_support`` via the Retriever facade. Mode comes from Settings."""
    text = query_text(failure)
    if not text:
        return failure.model_copy(update={"source_support": []})
    hits = await retriever.search(
        text,
        project_id,
        k=k,
        run_id=run_id if run_id is not None else failure.run_id,
    )
    refs: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        ref = format_source_ref(hit)
        if ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return failure.model_copy(update={"source_support": refs})
