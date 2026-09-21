"""Ops-lab victim backend: health + items. Independent of the skillforge package."""

import os

from fastapi import FastAPI
from pydantic import BaseModel

DEFAULT_HEALTH_PATH = "/health"


class HealthResponse(BaseModel):
    status: str


class Item(BaseModel):
    id: int
    name: str


class ItemsResponse(BaseModel):
    items: list[Item]


def normalize_health_path(raw: str) -> str:
    path = raw.strip() or DEFAULT_HEALTH_PATH
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def create_app() -> FastAPI:
    health_path = normalize_health_path(os.environ.get("HEALTH_PATH", DEFAULT_HEALTH_PATH))
    app = FastAPI(title="skillforge-ops-lab-backend")

    @app.get(health_path)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/api/items")
    async def list_items() -> ItemsResponse:
        return ItemsResponse(items=[Item(id=1, name="widget")])

    return app


app = create_app()
