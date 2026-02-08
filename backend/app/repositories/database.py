from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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
    channel_title TEXT NULL,
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
