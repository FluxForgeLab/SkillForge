"""Model adapters."""

from skillforge.models.adapters.base import ModelAdapter
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.adapters.openai_compatible import OpenAICompatibleAdapter

__all__ = ["FakeModelAdapter", "ModelAdapter", "OpenAICompatibleAdapter"]
