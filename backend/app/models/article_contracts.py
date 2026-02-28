from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    notes: str | None = Field(default=None, max_length=4000)
    source: str | None = Field(default=None, max_length=255)
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

    @field_validator("notes", "source", "session_id", mode="before")
    @classmethod
    def _normalize_optional_fields(cls, value: object) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("source", "session_id")
    @classmethod
    def _validate_safe_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[A-Za-z0-9._:/-]+", value):
            raise ValueError("value contains unsupported characters")
        return value

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


class ArticleReadStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: bool


class ArticleSyncStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_item_id: str
    sync_status: Literal["pending", "synced", "failed", "missing"]
    read_state: Literal["unread", "read"] | None = None
    wallabag_entry_id: int | None = None
    wallabag_entry_url: str | None = None
    sync_error: str | None = None
    synced_at: datetime | None = None
    last_push_attempt_at: datetime | None = None
    last_pull_attempt_at: datetime | None = None
    updated_at: datetime | None = None
