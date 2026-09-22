"""Wraps an adapter and rewrites a JSON array of full ModelResponse objects."""

from __future__ import annotations

import json
from pathlib import Path

from skillforge.models.adapters.base import ModelAdapter
from skillforge.models.types import ModelRequest, ModelResponse


class RecordingAdapter:
    def __init__(self, inner: ModelAdapter, path: Path) -> None:
        self._inner = inner
        self._path = path
        self._rows: list[dict[str, object]] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        response = await self._inner.generate(request)
        self._rows.append(response.model_dump(mode="json"))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._rows, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return response
