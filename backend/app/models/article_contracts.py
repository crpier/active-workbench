from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.models.tool_contracts import ToolError

ArticleStatus = Literal["captured", "processing", "readable", "failed"]
ArticleReadState = Literal["unread", "in_progress", "read"]


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


class ArticleCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2048)
    source: str = Field(default="manual_paste", max_length=64)
    shared_text: str | None = Field(default=None, max_length=4000)
    process_now: bool = True
    idempotency_key: UUID | None = None
    timezone: str = Field(default="Europe/Bucharest", max_length=120)
    session_id: str | None = Field(default=None, max_length=120)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        normalized = value.strip()
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("url contains control characters")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http/https URL")
        if parsed.username or parsed.password:
            raise ValueError("url must not contain credentials")
        return normalized

    @field_validator("source", mode="before")
    @classmethod
    def _normalize_source(cls, value: object) -> str:
        normalized = _normalize_optional_text(value)
        if normalized is None:
            return "manual_paste"
        lowered = normalized.lower()
        if not re.fullmatch(r"[a-z0-9_./:-]+", lowered):
            raise ValueError("source contains unsupported characters")
        return lowered

    @field_validator("shared_text", "session_id", mode="before")
    @classmethod
    def _normalize_optional_fields(cls, value: object) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def _normalize_timezone(cls, value: object) -> str:
        normalized = _normalize_optional_text(value)
        return normalized or "Europe/Bucharest"

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class ArticleCaptureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["saved", "already_exists", "failed"]
    request_id: UUID
    backend_status: str | None = None
    article_id: str | None = None
    article_status: ArticleStatus | None = None
    readable_available: bool = False
    bucket_item_id: str | None = None
    title: str | None = None
    canonical_url: str | None = None
    message: str | None = None
    error: ToolError | None = None


class ArticleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article_id: str
    bucket_item_id: str
    source_url: str
    canonical_url: str
    title: str | None = None
    author: str | None = None
    site_name: str | None = None
    published_at: str | None = None
    status: ArticleStatus
    read_state: ArticleReadState
    estimated_read_minutes: int | None = None
    progress_percent: int
    extraction_method: str | None = None
    llm_polished: bool
    captured_at: str
    updated_at: str
    last_error_code: str | None = None
    last_error_message: str | None = None


class ArticleListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    items: list[ArticleSummary]
    cursor: int
    next_cursor: int | None = None


class ArticleReadableResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article: ArticleSummary
    source_markdown: str | None = None
    llm_markdown: str | None = None
    default_markdown: str | None = None


class ArticleReadStateUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_state: ArticleReadState
    progress_percent: int | None = Field(default=None, ge=0, le=100)


class ArticleReadStateUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["updated"]
    article: ArticleSummary


class ArticleRetryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["queued"]
    article_id: str
    article_status: ArticleStatus


class ArticleDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["deleted"]
    article_id: str
