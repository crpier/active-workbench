"""Models for voice note capture."""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class CaptureRequest(BaseModel):
    """Request to capture a voice note."""

    text: str
    source: str = "google_assistant"
    timestamp: Optional[datetime] = None


class CaptureResponse(BaseModel):
    """Response after capturing a note."""

    status: str
    note_id: str
    note_path: str
