"""FastAPI application for Workbench backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from .api.capture import router as capture_router
from .config import get_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Workbench Backend",
    description="Voice note capture service for Active Workbench",
    version="0.1.0"
)

# CORS middleware (allow all origins for now, restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(capture_router)


@app.get("/")
async def root():
    """Root endpoint with service info."""
    config = get_config()
    return {
        "service": "workbench-backend",
        "version": "0.1.0",
        "vault_path": str(config.vault_path),
        "endpoints": {
            "health": "/health",
            "capture": "/api/capture"
        }
    }


@app.on_event("startup")
async def startup_event():
    """Log startup info."""
    config = get_config()
    logger.info(f"Starting Workbench Backend")
    logger.info(f"Vault path: {config.vault_path}")
    logger.info(f"Server: {config.host}:{config.port}")
