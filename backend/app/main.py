from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
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
            lock_path=settings.data_dir / "scheduler.lock",
        )
        scheduler.start()

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Active Workbench API", version="0.1.0", lifespan=app_lifespan)
    settings = get_settings()

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
    _mount_web_ui(app=app, web_dist_dir=settings.web_ui_dist_dir)
    app.add_api_route(
        "/health",
        health_check,
        methods=["GET"],
        tags=["system"],
        operation_id="health_check",
    )

    return app


def _mount_web_ui(*, app: FastAPI, web_dist_dir: Path) -> None:
    index_path = web_dist_dir / "index.html"
    expo_assets_path = web_dist_dir / "_expo"
    static_assets_path = web_dist_dir / "assets"
    favicon_path = web_dist_dir / "favicon.ico"

    if expo_assets_path.is_dir():
        app.mount("/_expo", StaticFiles(directory=expo_assets_path), name="expo_web_assets")
        app.mount("/app/_expo", StaticFiles(directory=expo_assets_path), name="expo_web_assets_scoped")

    if static_assets_path.is_dir():
        app.mount("/assets", StaticFiles(directory=static_assets_path), name="expo_web_static_assets")
        app.mount(
            "/app/assets",
            StaticFiles(directory=static_assets_path),
            name="expo_web_static_assets_scoped",
        )

    def _serve_index() -> Response:
        if index_path.is_file():
            return FileResponse(
                index_path,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
        return JSONResponse(
            status_code=404,
            content={
                "detail": (
                    "Web UI build not found. Build Expo web output and point "
                    "ACTIVE_WORKBENCH_WEB_UI_DIST_DIR to it."
                )
            },
        )

    def _web_ui_entry() -> Response:
        return _serve_index()

    def _web_ui_subpath(path: str) -> Response:
        _ = path
        return _serve_index()

    app.add_api_route(
        "/app",
        _web_ui_entry,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/app/{path:path}",
        _web_ui_subpath,
        methods=["GET"],
        include_in_schema=False,
    )

    if favicon_path.is_file():
        def _favicon() -> Response:
            return FileResponse(favicon_path)

        app.add_api_route(
            "/favicon.ico",
            _favicon,
            methods=["GET"],
            include_in_schema=False,
        )


app = create_app()
