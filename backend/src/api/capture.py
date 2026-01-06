"""Voice note capture API endpoint."""

from fastapi import APIRouter, BackgroundTasks
from datetime import datetime
import logging

from ..models.capture import CaptureRequest, CaptureResponse
from ..services.vault_writer import VaultWriter
from ..services.git_sync import GitSync
from ..config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["capture"])


@router.post("/capture")
async def capture_note(
    request: CaptureRequest,
    background_tasks: BackgroundTasks
) -> CaptureResponse:
    """Receive voice note and create in limbo/.

    Args:
        request: Capture request with text and metadata
        background_tasks: FastAPI background tasks for async git sync

    Returns:
        Response with note ID and path
    """
    config = get_config()
    vault_writer = VaultWriter(config.vault_path)

    timestamp = request.timestamp or datetime.now()

    # Create note file
    logger.info(f"Creating voice note from {request.source}: {request.text[:50]}...")
    note_path = vault_writer.create_voice_note(request.text, timestamp)

    # Schedule git sync in background (don't block response)
    git_sync = GitSync(config.vault_path)
    if git_sync.is_git_repo():
        background_tasks.add_task(git_sync.commit_and_push, note_path)
        logger.info(f"Scheduled git sync for: {note_path.name}")
    else:
        logger.warning("Vault is not a git repository, skipping sync")

    return CaptureResponse(
        status="captured",
        note_id=note_path.stem,
        note_path=str(note_path.relative_to(config.vault_path))
    )


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "workbench-backend",
        "version": "0.1.0"
    }
