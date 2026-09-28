"""Model / DGX runtime status."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from skillforge.api.deps import get_settings_dep
from skillforge.config import Settings
from skillforge.models.vllm_metrics import read_vllm_tokens_per_second

router = APIRouter(prefix="/model", tags=["model"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


class ModelStatusResponse(BaseModel):
    """Configured model identity. Rates come from vLLM /metrics or stay null."""

    model_config = ConfigDict(extra="forbid")

    model: str
    backend: str
    tokens_per_second: float | None = None
    memory_bytes: int | None = None


@router.get("/status", response_model=ModelStatusResponse)
async def model_status(settings: SettingsDep) -> ModelStatusResponse:
    """Return Settings identity. tokens/s is filled only from a vLLM histogram.

    memory_bytes stays null: the vLLM text format has no model-memory gauge.
    process_resident_memory_bytes is the API process, not the weights.
    """
    tokens_per_second = None
    resolved = settings.resolved_model()
    if resolved.adapter == "openai_compatible":
        tokens_per_second = await read_vllm_tokens_per_second(
            resolved.base_url,
            resolved.name,
        )
    return ModelStatusResponse(
        model=resolved.name,
        backend=resolved.adapter,
        tokens_per_second=tokens_per_second,
        memory_bytes=None,
    )
