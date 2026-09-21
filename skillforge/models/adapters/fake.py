"""Scripted model responses for tests and local development."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from skillforge.models.errors import ModelScriptExhaustedError
from skillforge.models.types import ModelRequest, ModelResponse


class FakeModelAdapter:
    def __init__(
        self,
        script: Iterable[ModelResponse] | None = None,
        *,
        default: ModelResponse | None = None,
    ) -> None:
        self._queue: deque[ModelResponse] = deque(script or [])
        self._default = default

    async def generate(self, request: ModelRequest) -> ModelResponse:
        del request
        if self._queue:
            return self._queue.popleft()
        if self._default is not None:
            return self._default
        raise ModelScriptExhaustedError()
