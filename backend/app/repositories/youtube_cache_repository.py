from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database


@dataclass(frozen=True)
class CachedLikeVideo:
    video_id: str
    title: str
    liked_at: str
    video_published_at: str | None
    description: str | None
    channel_title: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class CachedTranscript:
    video_id: str
    title: str
    transcript: str
    source: str
    segments: list[dict[str, object]]
    cached_at: datetime


class YouTubeCacheRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list_likes(self, *, limit: int) -> list[CachedLikeVideo]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    video_id,
                    title,
                    liked_at,
                    video_published_at,
                    description,
                    channel_title,
                    tags_json
                FROM youtube_likes_cache
                ORDER BY liked_at DESC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()

        videos: list[CachedLikeVideo] = []
        for row in rows:
            tags = _decode_tags(row["tags_json"])
            videos.append(
                CachedLikeVideo(
                    video_id=str(row["video_id"]),
                    title=str(row["title"]),
                    liked_at=str(row["liked_at"]),
                    video_published_at=_to_optional_str(row["video_published_at"]),
                    description=_to_optional_str(row["description"]),
                    channel_title=_to_optional_str(row["channel_title"]),
                    tags=tags,
                )
            )
        return videos

    def replace_likes(self, *, videos: list[CachedLikeVideo], max_items: int) -> None:
        now_iso = utc_now_iso()
        clamped_max_items = max(1, max_items)
        selected = videos[:clamped_max_items]

        with self._db.connection() as conn:
            conn.execute("DELETE FROM youtube_likes_cache")
            for video in selected:
                conn.execute(
                    """
                    INSERT INTO youtube_likes_cache
                    (
                        video_id,
                        title,
                        liked_at,
                        video_published_at,
                        description,
                        channel_title,
                        tags_json,
                        cached_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video.video_id,
                        video.title,
                        video.liked_at,
                        video.video_published_at,
                        video.description,
                        video.channel_title,
                        json.dumps(list(video.tags)),
                        now_iso,
                    ),
                )

            conn.execute(
                """
                INSERT INTO youtube_cache_state (cache_key, value_text, updated_at)
                VALUES ('likes_last_sync_at', ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    value_text = excluded.value_text,
                    updated_at = excluded.updated_at
                """,
                (now_iso, now_iso),
            )

    def get_likes_last_sync_at(self) -> datetime | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT value_text
                FROM youtube_cache_state
                WHERE cache_key = 'likes_last_sync_at'
                """,
            ).fetchone()

        if row is None:
            return None
        raw_value = row["value_text"]
        if not isinstance(raw_value, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw_value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def get_fresh_transcript(self, *, video_id: str, ttl_seconds: int) -> CachedTranscript | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT video_id, title, transcript, source, segments_json, cached_at
                FROM youtube_transcript_cache
                WHERE video_id = ?
                """,
                (video_id,),
            ).fetchone()

        if row is None:
            return None

        cached_at = _parse_timestamp(row["cached_at"])
        if cached_at is None:
            return None

        clamped_ttl = max(0, ttl_seconds)
        if datetime.now(UTC) - cached_at > timedelta(seconds=clamped_ttl):
            return None

        return CachedTranscript(
            video_id=str(row["video_id"]),
            title=str(row["title"]),
            transcript=str(row["transcript"]),
            source=str(row["source"]),
            segments=_decode_segments(row["segments_json"]),
            cached_at=cached_at,
        )

    def upsert_transcript(
        self,
        *,
        video_id: str,
        title: str,
        transcript: str,
        source: str,
        segments: list[dict[str, object]],
    ) -> None:
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO youtube_transcript_cache
                (video_id, title, transcript, source, segments_json, cached_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    title = excluded.title,
                    transcript = excluded.transcript,
                    source = excluded.source,
                    segments_json = excluded.segments_json,
                    cached_at = excluded.cached_at
                """,
                (video_id, title, transcript, source, json.dumps(segments), now_iso),
            )


def _to_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _decode_tags(raw_value: object) -> tuple[str, ...]:
    if not isinstance(raw_value, str):
        return ()
    try:
        parsed = cast(object, json.loads(raw_value))
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()

    tags: list[str] = []
    for item in cast(list[object], parsed):
        if isinstance(item, str):
            tags.append(item)
    return tuple(tags)


def _decode_segments(raw_value: object) -> list[dict[str, object]]:
    if not isinstance(raw_value, str):
        return []
    try:
        parsed = cast(object, json.loads(raw_value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    segments: list[dict[str, object]] = []
    for item in cast(list[object], parsed):
        if not isinstance(item, dict):
            continue
        item_dict = cast(dict[object, object], item)

        segment: dict[str, object] = {}
        text = item_dict.get("text")
        if isinstance(text, str):
            segment["text"] = text

        start = item_dict.get("start")
        if isinstance(start, (int, float)):
            segment["start"] = float(start)

        duration = item_dict.get("duration")
        if isinstance(duration, (int, float)):
            segment["duration"] = float(duration)

        if segment:
            segments.append(segment)
    return segments


def _parse_timestamp(raw_value: object) -> datetime | None:
    if not isinstance(raw_value, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
