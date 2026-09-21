"""Model adapter protocol."""

from __future__ import annotations

from typing import Protocol

from skillforge.models.types import ModelRequest, ModelResponse


class ModelAdapter(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse: ...
