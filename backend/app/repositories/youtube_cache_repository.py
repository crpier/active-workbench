from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection
from typing import cast

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database


def _empty_thumbnails() -> dict[str, str]:
    return {}


@dataclass(frozen=True)
class CachedLikeVideo:
    video_id: str
    title: str
    liked_at: str
    video_published_at: str | None = None
    description: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None
    duration_seconds: int | None = None
    category_id: str | None = None
    default_language: str | None = None
    default_audio_language: str | None = None
    caption_available: bool | None = None
    privacy_status: str | None = None
    licensed_content: bool | None = None
    made_for_kids: bool | None = None
    live_broadcast_content: str | None = None
    definition: str | None = None
    dimension: str | None = None
    thumbnails: dict[str, str] = field(default_factory=_empty_thumbnails)
    topic_categories: tuple[str, ...] = ()
    statistics_view_count: int | None = None
    statistics_like_count: int | None = None
    statistics_comment_count: int | None = None
    statistics_fetched_at: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CachedTranscript:
    video_id: str
    title: str
    transcript: str
    source: str
    segments: list[dict[str, object]]
    cached_at: datetime


@dataclass(frozen=True)
class TranscriptSyncCandidate:
    video_id: str
    title: str
    liked_at: str


class YouTubeCacheRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def count_likes(self) -> int:
        with self._db.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS value FROM youtube_likes_cache").fetchone()
        if row is None:
            return 0
        return max(0, _to_optional_int(row["value"]) or 0)

    def count_transcripts(self) -> int:
        with self._db.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS value FROM youtube_transcript_cache").fetchone()
        if row is None:
            return 0
        return max(0, _to_optional_int(row["value"]) or 0)

    def count_transcript_sync_state_by_status(self) -> dict[str, int]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS value
                FROM youtube_transcript_sync_state
                GROUP BY status
                """,
            ).fetchall()

        counts: dict[str, int] = {}
        for row in rows:
            raw_status = _to_optional_str(row["status"])
            if raw_status is None:
                continue
            counts[raw_status] = max(0, _to_optional_int(row["value"]) or 0)
        return counts

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
                    channel_id,
                    channel_title,
                    duration_seconds,
                    category_id,
                    default_language,
                    default_audio_language,
                    caption_available,
                    privacy_status,
                    licensed_content,
                    made_for_kids,
                    live_broadcast_content,
                    definition,
                    dimension,
                    thumbnails_json,
                    topic_categories_json,
                    statistics_view_count,
                    statistics_like_count,
                    statistics_comment_count,
                    statistics_fetched_at,
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
            thumbnails = _decode_thumbnails(row["thumbnails_json"])
            topic_categories = _decode_string_list(row["topic_categories_json"])
            videos.append(
                CachedLikeVideo(
                    video_id=str(row["video_id"]),
                    title=str(row["title"]),
                    liked_at=str(row["liked_at"]),
                    video_published_at=_to_optional_str(row["video_published_at"]),
                    description=_to_optional_str(row["description"]),
                    channel_id=_to_optional_str(row["channel_id"]),
                    channel_title=_to_optional_str(row["channel_title"]),
                    duration_seconds=_to_optional_int(row["duration_seconds"]),
                    category_id=_to_optional_str(row["category_id"]),
                    default_language=_to_optional_str(row["default_language"]),
                    default_audio_language=_to_optional_str(row["default_audio_language"]),
                    caption_available=_to_optional_bool(row["caption_available"]),
                    privacy_status=_to_optional_str(row["privacy_status"]),
                    licensed_content=_to_optional_bool(row["licensed_content"]),
                    made_for_kids=_to_optional_bool(row["made_for_kids"]),
                    live_broadcast_content=_to_optional_str(row["live_broadcast_content"]),
                    definition=_to_optional_str(row["definition"]),
                    dimension=_to_optional_str(row["dimension"]),
                    thumbnails=thumbnails,
                    topic_categories=topic_categories,
                    statistics_view_count=_to_optional_int(row["statistics_view_count"]),
                    statistics_like_count=_to_optional_int(row["statistics_like_count"]),
                    statistics_comment_count=_to_optional_int(row["statistics_comment_count"]),
                    statistics_fetched_at=_to_optional_str(row["statistics_fetched_at"]),
                    tags=tags,
                )
            )
        return videos

    def replace_likes(self, *, videos: list[CachedLikeVideo], max_items: int | None = None) -> None:
        now_iso = utc_now_iso()
        selected = videos if max_items is None else videos[: max(1, max_items)]

        with self._db.connection() as conn:
            conn.execute("DELETE FROM youtube_likes_cache")
            for video in selected:
                _upsert_like(conn=conn, video=video, cached_at=now_iso)
            _set_cache_state_value(
                conn=conn, key="likes_last_sync_at", value=now_iso, updated_at=now_iso
            )

    def upsert_likes(self, *, videos: list[CachedLikeVideo], max_items: int | None = None) -> None:
        if not videos:
            return

        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            for video in videos:
                _upsert_like(conn=conn, video=video, cached_at=now_iso)

            if max_items is not None:
                _trim_likes(conn=conn, max_items=max(1, max_items))
            _set_cache_state_value(
                conn=conn, key="likes_last_sync_at", value=now_iso, updated_at=now_iso
            )

    def trim_likes(self, *, max_items: int) -> None:
        clamped_max_items = max(1, max_items)
        with self._db.connection() as conn:
            _trim_likes(conn=conn, max_items=clamped_max_items)

    def purge_youtube_video(self, *, video_id: str) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM youtube_likes_cache WHERE video_id = ?",
                (video_id,),
            )
            conn.execute(
                "DELETE FROM youtube_transcript_cache WHERE video_id = ?",
                (video_id,),
            )
            conn.execute(
                "DELETE FROM youtube_transcript_sync_state WHERE video_id = ?",
                (video_id,),
            )

    def purge_likes_before(self, *, cutoff_liked_at: datetime) -> int:
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM youtube_likes_cache
                WHERE datetime(liked_at) < datetime(?)
                """,
                (_datetime_to_utc_iso(cutoff_liked_at),),
            )
            deleted = cursor.rowcount
        return max(0, deleted if isinstance(deleted, int) else 0)

    def purge_transcript_rows_not_in_likes(self) -> tuple[int, int]:
        with self._db.connection() as conn:
            transcript_cursor = conn.execute(
                """
                DELETE FROM youtube_transcript_cache
                WHERE video_id NOT IN (SELECT video_id FROM youtube_likes_cache)
                """
            )
            sync_cursor = conn.execute(
                """
                DELETE FROM youtube_transcript_sync_state
                WHERE video_id NOT IN (SELECT video_id FROM youtube_likes_cache)
                """
            )
            transcript_deleted = transcript_cursor.rowcount
            sync_deleted = sync_cursor.rowcount
        return (
            max(0, transcript_deleted if isinstance(transcript_deleted, int) else 0),
            max(0, sync_deleted if isinstance(sync_deleted, int) else 0),
        )

    def get_cache_state_value(self, key: str) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT value_text
                FROM youtube_cache_state
                WHERE cache_key = ?
                """,
                (key,),
            ).fetchone()

        if row is None:
            return None
        return _to_optional_str(row["value_text"])

    def set_cache_state_value(self, *, key: str, value: str) -> None:
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            _set_cache_state_value(conn=conn, key=key, value=value, updated_at=now_iso)

    def clear_cache_state_value(self, *, key: str) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                DELETE FROM youtube_cache_state
                WHERE cache_key = ?
                """,
                (key,),
            )

    def get_likes_last_sync_at(self) -> datetime | None:
        raw_value = self.get_cache_state_value("likes_last_sync_at")
        if raw_value is None:
            return None
        return _parse_timestamp(raw_value)

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

    def get_cached_transcript_texts(self, *, video_ids: list[str]) -> dict[str, str]:
        unique_ids: list[str] = []
        seen: set[str] = set()
        for video_id in video_ids:
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            unique_ids.append(video_id)

        if not unique_ids:
            return {}

        placeholders = ", ".join("?" for _ in unique_ids)
        query = (
            "SELECT video_id, transcript FROM youtube_transcript_cache "
            f"WHERE video_id IN ({placeholders})"
        )

        with self._db.connection() as conn:
            rows = conn.execute(query, tuple(unique_ids)).fetchall()

        transcripts: dict[str, str] = {}
        for row in rows:
            raw_video_id = _to_optional_str(row["video_id"])
            raw_transcript = _to_optional_str(row["transcript"])
            if raw_video_id is None or raw_transcript is None:
                continue
            transcripts[raw_video_id] = raw_transcript
        return transcripts

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

    def get_next_transcript_candidate(
        self,
        *,
        not_before: datetime,
    ) -> TranscriptSyncCandidate | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT likes.video_id, likes.title, likes.liked_at
                FROM youtube_likes_cache AS likes
                LEFT JOIN youtube_transcript_cache transcript
                    ON transcript.video_id = likes.video_id
                LEFT JOIN youtube_transcript_sync_state sync
                    ON sync.video_id = likes.video_id
                WHERE transcript.video_id IS NULL
                  AND (sync.next_attempt_at IS NULL OR sync.next_attempt_at <= ?)
                ORDER BY likes.liked_at DESC
                LIMIT 1
                """,
                (_datetime_to_utc_iso(not_before),),
            ).fetchone()

        if row is None:
            return None

        return TranscriptSyncCandidate(
            video_id=str(row["video_id"]),
            title=str(row["title"]),
            liked_at=str(row["liked_at"]),
        )

    def get_transcript_sync_attempts(self, *, video_id: str) -> int:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT attempts
                FROM youtube_transcript_sync_state
                WHERE video_id = ?
                """,
                (video_id,),
            ).fetchone()

        if row is None:
            return 0
        attempts = _to_optional_int(row["attempts"])
        return max(0, attempts or 0)

    def mark_transcript_sync_success(self, *, video_id: str) -> None:
        now = datetime.now(UTC)
        now_iso = _datetime_to_utc_iso(now)
        attempts = self.get_transcript_sync_attempts(video_id=video_id) + 1
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO youtube_transcript_sync_state
                (
                    video_id,
                    status,
                    attempts,
                    last_attempt_at,
                    next_attempt_at,
                    last_error
                )
                VALUES (?, 'done', ?, ?, ?, NULL)
                ON CONFLICT(video_id) DO UPDATE SET
                    status = excluded.status,
                    attempts = excluded.attempts,
                    last_attempt_at = excluded.last_attempt_at,
                    next_attempt_at = excluded.next_attempt_at,
                    last_error = excluded.last_error
                """,
                (video_id, attempts, now_iso, now_iso),
            )

    def mark_transcript_sync_failure(
        self,
        *,
        video_id: str,
        attempts: int,
        next_attempt_at: datetime,
        error: str,
    ) -> None:
        now = datetime.now(UTC)
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO youtube_transcript_sync_state
                (
                    video_id,
                    status,
                    attempts,
                    last_attempt_at,
                    next_attempt_at,
                    last_error
                )
                VALUES (?, 'retry_wait', ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    status = excluded.status,
                    attempts = excluded.attempts,
                    last_attempt_at = excluded.last_attempt_at,
                    next_attempt_at = excluded.next_attempt_at,
                    last_error = excluded.last_error
                """,
                (
                    video_id,
                    max(1, attempts),
                    _datetime_to_utc_iso(now),
                    _datetime_to_utc_iso(next_attempt_at),
                    error[:1000],
                ),
            )


def _to_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _decode_tags(raw_value: object) -> tuple[str, ...]:
    return _decode_string_list(raw_value)


def _decode_string_list(raw_value: object) -> tuple[str, ...]:
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


def _decode_thumbnails(raw_value: object) -> dict[str, str]:
    if not isinstance(raw_value, str):
        return {}
    try:
        parsed = cast(object, json.loads(raw_value))
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}

    thumbnails: dict[str, str] = {}
    for raw_key, raw_item in cast(dict[object, object], parsed).items():
        if not isinstance(raw_key, str):
            continue
        if isinstance(raw_item, str) and raw_item.strip():
            thumbnails[raw_key] = raw_item
    return thumbnails


def _to_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _to_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _set_cache_state_value(*, conn: Connection, key: str, value: str, updated_at: str) -> None:
    conn.execute(
        """
        INSERT INTO youtube_cache_state (cache_key, value_text, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            value_text = excluded.value_text,
            updated_at = excluded.updated_at
        """,
        (key, value, updated_at),
    )


def _trim_likes(*, conn: Connection, max_items: int) -> None:
    conn.execute(
        """
        DELETE FROM youtube_likes_cache
        WHERE video_id NOT IN (
            SELECT video_id
            FROM youtube_likes_cache
            ORDER BY liked_at DESC
            LIMIT ?
        )
        """,
        (max_items,),
    )


def _upsert_like(*, conn: Connection, video: CachedLikeVideo, cached_at: str) -> None:
    conn.execute(
        """
        INSERT INTO youtube_likes_cache
        (
            video_id,
            title,
            liked_at,
            video_published_at,
            description,
            channel_id,
            channel_title,
            duration_seconds,
            category_id,
            default_language,
            default_audio_language,
            caption_available,
            privacy_status,
            licensed_content,
            made_for_kids,
            live_broadcast_content,
            definition,
            dimension,
            thumbnails_json,
            topic_categories_json,
            statistics_view_count,
            statistics_like_count,
            statistics_comment_count,
            statistics_fetched_at,
            tags_json,
            cached_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            title = excluded.title,
            liked_at = excluded.liked_at,
            video_published_at = excluded.video_published_at,
            description = excluded.description,
            channel_id = excluded.channel_id,
            channel_title = excluded.channel_title,
            duration_seconds = excluded.duration_seconds,
            category_id = excluded.category_id,
            default_language = excluded.default_language,
            default_audio_language = excluded.default_audio_language,
            caption_available = excluded.caption_available,
            privacy_status = excluded.privacy_status,
            licensed_content = excluded.licensed_content,
            made_for_kids = excluded.made_for_kids,
            live_broadcast_content = excluded.live_broadcast_content,
            definition = excluded.definition,
            dimension = excluded.dimension,
            thumbnails_json = excluded.thumbnails_json,
            topic_categories_json = excluded.topic_categories_json,
            statistics_view_count = excluded.statistics_view_count,
            statistics_like_count = excluded.statistics_like_count,
            statistics_comment_count = excluded.statistics_comment_count,
            statistics_fetched_at = excluded.statistics_fetched_at,
            tags_json = excluded.tags_json,
            cached_at = excluded.cached_at
        """,
        (
            video.video_id,
            video.title,
            video.liked_at,
            video.video_published_at,
            video.description,
            video.channel_id,
            video.channel_title,
            video.duration_seconds,
            video.category_id,
            video.default_language,
            video.default_audio_language,
            _bool_to_int(video.caption_available),
            video.privacy_status,
            _bool_to_int(video.licensed_content),
            _bool_to_int(video.made_for_kids),
            video.live_broadcast_content,
            video.definition,
            video.dimension,
            json.dumps(video.thumbnails),
            json.dumps(list(video.topic_categories)),
            video.statistics_view_count,
            video.statistics_like_count,
            video.statistics_comment_count,
            video.statistics_fetched_at,
            json.dumps(list(video.tags)),
            cached_at,
        ),
    )


def _bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


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


def _datetime_to_utc_iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()
