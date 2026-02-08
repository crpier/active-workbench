from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.routes import router

app = FastAPI(title="Active Workbench API", version="0.1.0")
app.include_router(router)


@app.get("/health", tags=["system"], operation_id="health_check")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
