from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.dependencies import get_dispatcher, get_settings
from backend.app.services.scheduler_service import SchedulerService


def health_check() -> dict[str, str]:
    return {"status": "ok"}


@asynccontextmanager
async def app_lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    scheduler: SchedulerService | None = None

    if settings.scheduler_enabled:
        scheduler = SchedulerService(
            dispatcher=get_dispatcher(),
            poll_interval_seconds=settings.scheduler_poll_interval_seconds,
        )
        scheduler.start()

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Active Workbench API", version="0.1.0", lifespan=app_lifespan)
    app.include_router(router)
    app.add_api_route(
        "/health",
        health_check,
        methods=["GET"],
        tags=["system"],
        operation_id="health_check",
    )

    return app


app = create_app()
