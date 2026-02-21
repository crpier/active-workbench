from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from structlog.contextvars import bind_contextvars, reset_contextvars

from backend.app.api.routes import router
from backend.app.dependencies import get_dispatcher, get_settings, get_telemetry
from backend.app.logging_config import configure_application_logging
from backend.app.services.scheduler_service import SchedulerService


def health_check() -> dict[str, str]:
    return {"status": "ok"}


@asynccontextmanager
async def app_lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_application_logging(settings)
    telemetry = get_telemetry()
    scheduler: SchedulerService | None = None

    if settings.scheduler_enabled:
        dispatcher = get_dispatcher()
        scheduler = SchedulerService(
            dispatcher=dispatcher,
            poll_interval_seconds=settings.scheduler_poll_interval_seconds,
            transcript_poll_interval_seconds=(
                settings.youtube_transcript_scheduler_poll_interval_seconds
            ),
            youtube_service=dispatcher.youtube_service,
            telemetry=telemetry,
        )
        scheduler.start()

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Active Workbench API", version="0.1.0", lifespan=app_lifespan)

    async def request_context_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        telemetry = get_telemetry()
        incoming_request_id = request.headers.get("X-Request-ID")
        request_id = (
            incoming_request_id.strip()
            if isinstance(incoming_request_id, str) and incoming_request_id.strip()
            else str(uuid4())
        )
        context_tokens = bind_contextvars(
            http_request_id=request_id,
            http_method=request.method,
            http_path=request.url.path,
        )
        started_at = perf_counter()
        telemetry.emit(
            "http.request.start",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        except Exception as exc:
            telemetry.emit(
                "http.request.error",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                duration_ms=int((perf_counter() - started_at) * 1000),
                error_type=type(exc).__name__,
            )
            raise
        else:
            response.headers["X-Request-ID"] = request_id
            telemetry.emit(
                "http.request.finish",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                duration_ms=int((perf_counter() - started_at) * 1000),
                status_code=response.status_code,
            )
            return response
        finally:
            reset_contextvars(**context_tokens)

    app.middleware("http")(request_context_middleware)
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
