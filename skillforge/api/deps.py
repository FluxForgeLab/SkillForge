"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from skillforge.config import Settings, get_settings


def get_settings_dep(request: Request) -> Settings:
    stored = getattr(request.app.state, "settings", None)
    if isinstance(stored, Settings):
        return stored
    return get_settings()
