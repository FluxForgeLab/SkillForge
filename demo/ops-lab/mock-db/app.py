"""Ops-lab mock-db: stay-up health endpoint. Independent of the skillforge package."""

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


def create_app() -> FastAPI:
    app = FastAPI(title="skillforge-ops-lab-mock-db")

    @app.get("/health")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
