"""Model / DGX runtime status (settings snapshot; metrics filled in C10.2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from skillforge.api.deps import get_settings_dep
from skillforge.config import Settings

router = APIRouter(prefix="/model", tags=["model"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


class ModelStatusResponse(BaseModel):
    """Configured model identity; tokens/s and memory are null until measured."""

    model_config = ConfigDict(extra="forbid")

    model: str
    backend: str
    tokens_per_second: float | None = None
    memory_bytes: int | None = None


@router.get("/status", response_model=ModelStatusResponse)
async def model_status(settings: SettingsDep) -> ModelStatusResponse:
    """Return current Settings model identity only — no secrets, no invented metrics."""
    return ModelStatusResponse(
        model=settings.model_name,
        backend=settings.model_adapter,
        tokens_per_second=None,
        memory_bytes=None,
    )
