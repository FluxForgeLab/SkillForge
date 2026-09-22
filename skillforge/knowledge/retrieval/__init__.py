"""Retrieval facade. Other modules import only these names."""

from skillforge.knowledge.retrieval.base import RetrievalHit, RetrievalQuery
from skillforge.knowledge.retrieval.retriever import Retriever

__all__ = [
    "RetrievalHit",
    "RetrievalQuery",
    "Retriever",
]
