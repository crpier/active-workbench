from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

BUCKET_ITEMS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bucket_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT NOT NULL,
    canonical_id TEXT NULL,
    metadata_json TEXT NOT NULL,
    source_refs_json TEXT NOT NULL,
    added_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT NULL,
    last_recommended_at TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_bucket_items_status_domain
ON bucket_items(status, domain);

CREATE INDEX IF NOT EXISTS idx_bucket_items_status_added
ON bucket_items(status, added_at DESC);
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    tool_name TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tool_name, idempotency_key)
);

CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    content_json TEXT NOT NULL,
    source_refs_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS memory_undo_tokens (
    undo_token TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    consumed_at TEXT NULL,
    FOREIGN KEY(memory_id) REFERENCES memory_entries(id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    run_at TEXT NOT NULL,
    timezone TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    recurrence TEXT NULL,
    last_run_at TEXT NULL,
    completed_at TEXT NULL,
    result_json TEXT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_run_at ON jobs(status, run_at);

CREATE TABLE IF NOT EXISTS youtube_quota_daily (
    date_utc TEXT PRIMARY KEY,
    units_used INTEGER NOT NULL,
    calls INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_quota_by_tool_daily (
    date_utc TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    units_used INTEGER NOT NULL,
    calls INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (date_utc, tool_name)
);

CREATE TABLE IF NOT EXISTS youtube_cache_state (
    cache_key TEXT PRIMARY KEY,
    value_text TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_likes_cache (
    video_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    liked_at TEXT NOT NULL,
    video_published_at TEXT NULL,
    description TEXT NULL,
    channel_id TEXT NULL,
    channel_title TEXT NULL,
    duration_seconds INTEGER NULL,
    category_id TEXT NULL,
    default_language TEXT NULL,
    default_audio_language TEXT NULL,
    caption_available INTEGER NULL,
    privacy_status TEXT NULL,
    licensed_content INTEGER NULL,
    made_for_kids INTEGER NULL,
    live_broadcast_content TEXT NULL,
    definition TEXT NULL,
    dimension TEXT NULL,
    thumbnails_json TEXT NOT NULL,
    topic_categories_json TEXT NOT NULL,
    statistics_view_count INTEGER NULL,
    statistics_like_count INTEGER NULL,
    statistics_comment_count INTEGER NULL,
    statistics_fetched_at TEXT NULL,
    tags_json TEXT NOT NULL,
    cached_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_youtube_likes_cache_liked_at
ON youtube_likes_cache(liked_at DESC);

CREATE TABLE IF NOT EXISTS youtube_transcript_cache (
    video_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    transcript TEXT NOT NULL,
    source TEXT NOT NULL,
    segments_json TEXT NOT NULL,
    cached_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_transcript_sync_state (
    video_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    last_attempt_at TEXT NOT NULL,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_youtube_transcript_sync_state_next_attempt
ON youtube_transcript_sync_state(next_attempt_at, status);

CREATE TABLE IF NOT EXISTS bucket_tmdb_quota_daily (
    date_utc TEXT PRIMARY KEY,
    calls INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)
            _maybe_migrate_bucket_items_schema(conn)
            conn.executescript(BUCKET_ITEMS_SCHEMA_SQL)


def _maybe_migrate_bucket_items_schema(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "bucket_items")
    if not columns:
        return

    # Old schema carried many first-class media fields.
    if "notes" in columns:
        rows = conn.execute("SELECT * FROM bucket_items").fetchall()
        conn.execute("ALTER TABLE bucket_items RENAME TO bucket_items_old_schema")
        conn.executescript(BUCKET_ITEMS_SCHEMA_SQL)

        for row in rows:
            metadata = _load_object_dict(row["metadata_json"])
            source_refs_json = _ensure_json_list_text(row["source_refs_json"])

            notes = _as_text_or_none(row["notes"])
            if notes is not None:
                metadata["notes"] = notes
            year = _as_int_or_none(row["year"])
            if year is not None:
                metadata["year"] = year
            duration_minutes = _as_int_or_none(row["duration_minutes"])
            if duration_minutes is not None:
                metadata["duration_minutes"] = duration_minutes
            rating = _as_float_or_none(row["rating"])
            if rating is not None:
                metadata["rating"] = rating
            popularity = _as_float_or_none(row["popularity"])
            if popularity is not None:
                metadata["popularity"] = popularity

            genres = _load_str_list(row["genres_json"])
            if genres:
                metadata["genres"] = genres
            tags = _load_str_list(row["tags_json"])
            if tags:
                metadata["tags"] = tags
            providers = _load_str_list(row["providers_json"])
            if providers:
                metadata["providers"] = providers

            external_url = _as_text_or_none(row["external_url"])
            if external_url is not None:
                metadata["external_url"] = external_url
            confidence = _as_float_or_none(row["confidence"])
            if confidence is not None:
                metadata["confidence"] = confidence

            conn.execute(
                """
                INSERT INTO bucket_items (
                    id, title, normalized_title, domain, status, canonical_id, metadata_json,
                    source_refs_json, added_at, updated_at, completed_at, last_recommended_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row["id"]),
                    str(row["title"]),
                    str(row["normalized_title"]),
                    str(row["domain"]),
                    str(row["status"]),
                    _as_text_or_none(row["canonical_id"]),
                    json.dumps(metadata, sort_keys=True, ensure_ascii=True),
                    source_refs_json,
                    str(row["added_at"]),
                    str(row["updated_at"]),
                    _as_text_or_none(row["completed_at"]),
                    _as_text_or_none(row["last_recommended_at"]),
                ),
            )

        conn.execute("DROP TABLE bucket_items_old_schema")
        return

    # Remove legacy compatibility column carried by hybrid schema.
    if "legacy_path" in columns:
        rows = conn.execute("SELECT * FROM bucket_items").fetchall()
        conn.execute("ALTER TABLE bucket_items RENAME TO bucket_items_with_legacy_path")
        conn.executescript(BUCKET_ITEMS_SCHEMA_SQL)

        for row in rows:
            metadata = _load_object_dict(row["metadata_json"])
            metadata.pop("legacy_markdown", None)
            conn.execute(
                """
                INSERT INTO bucket_items (
                    id, title, normalized_title, domain, status, canonical_id, metadata_json,
                    source_refs_json, added_at, updated_at, completed_at, last_recommended_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row["id"]),
                    str(row["title"]),
                    str(row["normalized_title"]),
                    str(row["domain"]),
                    str(row["status"]),
                    _as_text_or_none(row["canonical_id"]),
                    json.dumps(metadata, sort_keys=True, ensure_ascii=True),
                    _ensure_json_list_text(row["source_refs_json"]),
                    str(row["added_at"]),
                    str(row["updated_at"]),
                    _as_text_or_none(row["completed_at"]),
                    _as_text_or_none(row["last_recommended_at"]),
                ),
            )

        conn.execute("DROP TABLE bucket_items_with_legacy_path")


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _as_text_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return str(value)


def _as_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _as_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _load_object_dict(raw: object) -> dict[str, object]:
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        raw_dict = cast(dict[object, object], parsed)
        output: dict[str, object] = {}
        for key, value in raw_dict.items():
            output[str(key)] = value
        return output
    return {}


def _load_str_list(raw: object) -> list[str]:
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    raw_items = cast(list[object], parsed)
    values: list[str] = []
    for item in raw_items:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                values.append(stripped)
    return values


def _ensure_json_list_text(raw: object) -> str:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return "[]"
        if isinstance(parsed, list):
            return json.dumps(parsed, sort_keys=True, ensure_ascii=True)
    return "[]"
