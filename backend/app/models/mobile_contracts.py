from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.models.tool_contracts import ToolError


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


class ShareArticleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    shared_text: str | None = None
    source_app: str | None = None
    idempotency_key: UUID | None = None
    timezone: str = Field(default="Europe/Bucharest")
    session_id: str | None = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http/https URL")
        return normalized

    @field_validator("shared_text", "source_app", "session_id", mode="before")
    @classmethod
    def _normalize_optional_fields(cls, value: object) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def _normalize_timezone(cls, value: object) -> str:
        normalized = _normalize_optional_text(value)
        return normalized or "Europe/Bucharest"


class ShareArticleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["saved", "already_exists", "needs_clarification", "failed"]
    request_id: UUID
    backend_status: str | None = None
    bucket_item_id: str | None = None
    title: str | None = None
    canonical_url: str | None = None
    message: str | None = None
    candidates: list[dict[str, object]] = Field(default_factory=lambda: [])
    error: ToolError | None = None
