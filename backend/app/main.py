from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.routes import router


def health_check() -> dict[str, str]:
    return {"status": "ok"}


def create_app() -> FastAPI:
    app = FastAPI(title="Active Workbench API", version="0.1.0")
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
