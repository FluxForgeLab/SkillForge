"""ModelGateway and adapter factory."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from skillforge.config import Settings, get_settings
from skillforge.domain.enums import TraceEventType
from skillforge.models.adapters.base import ModelAdapter
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.adapters.openai_compatible import OpenAICompatibleAdapter
from skillforge.models.errors import ModelError, ModelInvocationError
from skillforge.models.types import (
    ModelRequest,
    ModelResponse,
    request_trace_payload,
    response_trace_payload,
)
from skillforge.tracing.bus import EventBus
from skillforge.tracing.emitter import emit, get_bus
from skillforge.tracing.sink import TraceSink


class ModelGateway:
    def __init__(
        self,
        adapter: ModelAdapter,
        *,
        settings: Settings | None = None,
        bus: EventBus | None = None,
        sink: TraceSink | None = None,
    ) -> None:
        self._adapter = adapter
        self._settings = settings if settings is not None else get_settings()
        self._bus = bus if bus is not None else get_bus()
        self._sink = sink

    async def generate(self, request: ModelRequest) -> ModelResponse:
        await emit(
            request.run_id,
            TraceEventType.MODEL_REQUEST,
            name="generate",
            input=request_trace_payload(request),
            stage=request.stage,
            bus=self._bus,
            sink=self._sink,
        )
        started = time.perf_counter()
        try:
            response = await self._adapter.generate(request)
        except ModelError:
            raise
        except Exception as exc:
            raise ModelInvocationError(str(exc)) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        await emit(
            request.run_id,
            TraceEventType.MODEL_RESPONSE,
            name="generate",
            output=response_trace_payload(response),
            duration_ms=duration_ms,
            stage=request.stage,
            bus=self._bus,
            sink=self._sink,
        )
        return response


def build_adapter(settings: Settings) -> ModelAdapter:
    name = settings.model_adapter
    if name == "fake":
        return FakeModelAdapter(
            default=ModelResponse(
                content="(fake adapter: configure a script for multi-step runs)",
                finish_reason="stop",
            ),
        )
    if name == "openai_compatible":
        return OpenAICompatibleAdapter(
            base_url=settings.model_base_url,
            api_key=settings.model_api_key.get_secret_value(),
            default_model=settings.model_name,
            default_temperature=settings.temperature,
            default_seed=settings.seed,
        )
    if name in ("stepfun_local", "stepfun_api"):
        raise NotImplementedError(
            f"model adapter {name!r} is not implemented yet (planned after DGX spike)",
        )
    raise ValueError(f"unknown model adapter: {name!r}")


@lru_cache(maxsize=1)
def get_model_gateway() -> ModelGateway:
    settings = get_settings()
    return ModelGateway(build_adapter(settings), settings=settings)


def load_fake_script(path: Path) -> list[ModelResponse]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = "fake script must be a JSON array of ModelResponse objects"
        raise ValueError(msg)
    return [ModelResponse.model_validate(item) for item in raw]


def fake_adapter_from_script(
    script: Iterable[ModelResponse] | Path,
    *,
    default: ModelResponse | None = None,
) -> ModelAdapter:
    if isinstance(script, Path):
        return FakeModelAdapter(load_fake_script(script), default=default)
    return FakeModelAdapter(script, default=default)
