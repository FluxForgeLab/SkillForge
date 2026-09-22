"""Demo fault inject and reset. Host scripts stay behind replaceable callables."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from skillforge.cli import inject_fault, reset_fault, resolve_fault

router = APIRouter(prefix="/demo", tags=["demo"])

InjectFn = Callable[[str], None]
ResetFn = Callable[[], None]


class InjectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fault_id: str


class ResetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


def get_lab_inject() -> InjectFn:
    return inject_fault


def get_lab_reset() -> ResetFn:
    return reset_fault


@router.post("/faults/{fault_id}/inject", response_model=InjectResponse)
async def inject_demo_fault(
    fault_id: str,
    inject: Annotated[InjectFn, Depends(get_lab_inject)],
) -> InjectResponse:
    try:
        resolved = resolve_fault(fault_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        await asyncio.to_thread(inject, resolved)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return InjectResponse(fault_id=resolved)


@router.post("/reset", response_model=ResetResponse)
async def reset_demo(
    reset: Annotated[ResetFn, Depends(get_lab_reset)],
) -> ResetResponse:
    try:
        await asyncio.to_thread(reset)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ResetResponse(status="reset")
