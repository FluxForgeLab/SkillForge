"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from skillforge.api.errors import register_exception_handlers
from skillforge.api.routers.demo import router as demo_router
from skillforge.api.routers.projects import router as projects_router
from skillforge.api.routers.runs import router as runs_router
from skillforge.api.ws import ConnectionManager
from skillforge.api.ws import router as ws_router
from skillforge.config import Settings, get_settings
from skillforge.db.init import initialize_database
from skillforge.domain.entities import TraceEvent
from skillforge.tracing.bus import EventBus
from skillforge.tracing.emitter import get_bus


def create_app(
    settings: Settings | None = None,
    *,
    bus: EventBus | None = None,
) -> FastAPI:
    resolved_settings = settings if settings is not None else get_settings()
    resolved_bus = bus if bus is not None else get_bus()
    ws_manager = ConnectionManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.ws_manager = ws_manager

        async def forward(event: TraceEvent) -> None:
            await ws_manager.broadcast(event)

        unsubscribe = resolved_bus.subscribe(forward)
        initialize_database(resolved_settings.sqlite_path)
        try:
            yield
        finally:
            unsubscribe()

    app = FastAPI(title="SkillForge", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.ws_manager = ws_manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "skillforge"}

    app.include_router(ws_router, prefix="/api")
    app.include_router(projects_router, prefix="/api")
    app.include_router(demo_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")

    return app


app = create_app()
