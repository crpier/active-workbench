from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.app.repositories.youtube_cache_repository import (
    WATCH_LATER_STATUS_ACTIVE,
    WATCH_LATER_STATUS_REMOVED_NOT_LIKED,
    WATCH_LATER_STATUS_REMOVED_WATCHED,
    CachedLikeVideo,
    CachedWatchLaterVideo,
    YouTubeCacheRepository,
)


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    published_at: str
    liked_at: str | None = None
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
    thumbnails: dict[str, str] | None = None
    topic_categories: tuple[str, ...] = ()
    statistics_view_count: int | None = None
    statistics_like_count: int | None = None
    statistics_comment_count: int | None = None
    statistics_fetched_at: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class YouTubeTranscript:
    video_id: str
    title: str
    transcript: str
    source: str
    segments: list[dict[str, Any]]


@dataclass(frozen=True)
class YouTubeListRecentResult:
    videos: list[YouTubeVideo]
    estimated_api_units: int
    cache_hit: bool
    refreshed: bool
    cache_miss: bool = False
    recent_probe_applied: bool = False
    recent_probe_pages_used: int = 0
    cursor: int = 0
    next_cursor: int | None = None
    has_more: bool = False
    total_matches: int = 0
    applied_limit: int = 0


@dataclass(frozen=True)
class YouTubeTranscriptResult:
    transcript: YouTubeTranscript
    estimated_api_units: int
    cache_hit: bool
    provider_request_id: str | None = None


@dataclass(frozen=True)
class YouTubeRecentContentMatch:
    video: YouTubeVideo
    score: int
    matched_in: tuple[str, ...]
    snippet: str | None


@dataclass(frozen=True)
class YouTubeRecentContentSearchResult:
    matches: list[YouTubeRecentContentMatch]
    recent_videos_count: int
    transcripts_available_count: int
    transcript_coverage_percent: int
    estimated_api_units: int
    cache_miss: bool
    recent_probe_applied: bool
    recent_probe_pages_used: int


@dataclass(frozen=True)
class YouTubeWatchLaterRecommendationResult:
    video: YouTubeVideo | None
    score: int
    reason: str


class YouTubeServiceError(Exception):
    pass


class TranscriptProviderError(YouTubeServiceError):
    pass


class SupadataTranscriptError(TranscriptProviderError):
    pass


class YouTubeRateLimitedError(YouTubeServiceError):
    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int,
        scope: str,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = max(1, retry_after_seconds)
        self.scope = scope


class TranscriptProviderBlockedError(TranscriptProviderError):
    pass


class YouTubeTranscriptIpBlockedError(TranscriptProviderBlockedError):
    # Backward-compatible alias retained for tests and callers.
    pass


class TranscriptExcludedVideoError(TranscriptProviderError):
    pass


@dataclass(frozen=True)
class _OAuthLikedFetch:
    videos: list[YouTubeVideo]
    estimated_api_units: int


@dataclass(frozen=True)
class _OAuthLikedPageFetch:
    videos: list[YouTubeVideo]
    next_page_token: str | None
    estimated_api_units: int
    excluded_members_only_video_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _VideoSnippet:
    title: str
    description: str | None


@dataclass(frozen=True)
class _VideoMetadata:
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
    thumbnails: dict[str, str] | None = None
    topic_categories: tuple[str, ...] = ()
    statistics_view_count: int | None = None
    statistics_like_count: int | None = None
    statistics_comment_count: int | None = None
    statistics_fetched_at: str | None = None
    tags: tuple[str, ...] = ()


LOGGER = logging.getLogger("active_workbench.youtube")

QUERY_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "am",
        "an",
        "are",
        "about",
        "and",
        "as",
        "at",
        "been",
        "but",
        "can",
        "could",
        "did",
        "do",
        "does",
        "find",
        "for",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "ive",
        "liked",
        "make",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "recently",
        "saw",
        "seen",
        "should",
        "some",
        "recent",
        "somewhere",
        "summarize",
        "summary",
        "that",
        "tell",
        "the",
        "them",
        "then",
        "there",
        "this",
        "to",
        "up",
        "video",
        "want",
        "was",
        "watched",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "would",
        "you",
    }
)

LIKES_BACKGROUND_LAST_RUN_AT_KEY = "likes_background_last_run_at"
LIKES_BACKGROUND_BACKFILL_NEXT_PAGE_TOKEN_KEY = "likes_background_backfill_next_page_token"
LIKES_RECENT_PROBE_RATE_LIMIT_PAUSED_UNTIL_KEY = "likes_recent_probe_rate_limit_paused_until"
LIKES_RECENT_PROBE_RATE_LIMIT_STREAK_KEY = "likes_recent_probe_rate_limit_streak"
WATCH_LATER_METADATA_BACKGROUND_LAST_RUN_AT_KEY = "watch_later_metadata_background_last_run_at"
TRANSCRIPTS_BACKGROUND_LAST_RUN_AT_KEY = "transcripts_background_last_run_at"
TRANSCRIPTS_BACKGROUND_IP_BLOCK_PAUSED_UNTIL_KEY = "transcripts_background_ip_block_paused_until"
TRANSCRIPTS_BACKGROUND_IP_BLOCK_STREAK_KEY = "transcripts_background_ip_block_streak"
TRANSCRIPTS_YOUTUBE_API_FALLBACK_LAST_QUERY_AT_KEY = (
    "transcripts_youtube_api_fallback_last_query_at"
)
LIKES_RECENT_PROBE_RATE_LIMIT_BASE_SECONDS = 900
LIKES_RECENT_PROBE_RATE_LIMIT_MAX_SECONDS = 86_400
YOUTUBE_TRANSCRIPT_API_FALLBACK_MIN_INTERVAL_SECONDS = 600
ISO8601_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
SUPADATA_PENDING_JOB_STATUSES: frozenset[str] = frozenset(
    {
        "queued",
        "pending",
        "processing",
        "running",
        "in_progress",
        "in progress",
    }
)
SUPADATA_GENERATE_FALLBACK_POLL_INTERVAL_SECONDS = 30.0


class YouTubeService:
    def __init__(
        self,
        mode: str,
        data_dir: Path,
        *,
        cache_repository: YouTubeCacheRepository | None = None,
        likes_cache_ttl_seconds: int = 600,
        likes_recent_guard_seconds: int = 45,
        likes_cache_max_items: int = 500,
        likes_background_sync_enabled: bool = True,
        likes_background_min_interval_seconds: int = 120,
        likes_background_hot_pages: int = 2,
        likes_background_backfill_pages_per_run: int = 1,
        likes_background_page_size: int = 50,
        likes_cutoff_date: date = date(2024, 10, 20),
        likes_background_target_items: int = 1_000,
        watch_later_metadata_sync_enabled: bool = True,
        watch_later_metadata_sync_min_interval_seconds: int = 900,
        watch_later_metadata_sync_batch_size: int = 30,
        transcript_cache_ttl_seconds: int = 86_400,
        transcript_background_sync_enabled: bool = True,
        transcript_background_min_interval_seconds: int = 120,
        transcript_background_recent_limit: int = 1_000,
        transcript_background_backoff_base_seconds: int = 300,
        transcript_background_backoff_max_seconds: int = 86_400,
        transcript_background_ip_block_pause_seconds: int = 7_200,
        oauth_token_path: Path | None = None,
        oauth_client_secret_path: Path | None = None,
        supadata_api_key: str | None = None,
        supadata_base_url: str = "https://api.supadata.ai/v1",
        supadata_transcript_mode: str = "native",
        supadata_http_timeout_seconds: float = 30.0,
        supadata_poll_interval_seconds: float = 1.0,
        supadata_poll_max_attempts: int = 30,
    ) -> None:
        normalized_mode = mode.strip().lower()
        if normalized_mode != "oauth":
            raise YouTubeServiceError(
                "Unsupported YouTube mode. Only OAuth-backed mode is available."
            )
        self._data_dir = data_dir
        self._cache_repository = cache_repository
        self._likes_cache_ttl_seconds = max(0, likes_cache_ttl_seconds)
        self._likes_recent_guard_seconds = max(0, likes_recent_guard_seconds)
        self._likes_cache_max_items = max(25, likes_cache_max_items)
        self._likes_background_sync_enabled = likes_background_sync_enabled
        self._likes_background_min_interval_seconds = max(0, likes_background_min_interval_seconds)
        self._likes_background_hot_pages = max(1, likes_background_hot_pages)
        self._likes_background_backfill_pages_per_run = max(
            1, likes_background_backfill_pages_per_run
        )
        self._likes_background_page_size = max(1, min(50, likes_background_page_size))
        self._likes_cutoff_date = likes_cutoff_date
        self._likes_cutoff_datetime = datetime(
            likes_cutoff_date.year,
            likes_cutoff_date.month,
            likes_cutoff_date.day,
            tzinfo=UTC,
        )
        self._likes_background_target_items = max(
            self._likes_background_page_size,
            likes_background_target_items,
        )
        self._watch_later_metadata_sync_enabled = watch_later_metadata_sync_enabled
        self._watch_later_metadata_sync_min_interval_seconds = max(
            0, watch_later_metadata_sync_min_interval_seconds
        )
        self._watch_later_metadata_sync_batch_size = max(1, watch_later_metadata_sync_batch_size)
        self._transcript_cache_ttl_seconds = max(0, transcript_cache_ttl_seconds)
        self._transcript_background_sync_enabled = transcript_background_sync_enabled
        self._transcript_background_min_interval_seconds = max(
            0, transcript_background_min_interval_seconds
        )
        self._transcript_background_recent_limit = max(1, transcript_background_recent_limit)
        self._transcript_background_backoff_base_seconds = max(
            1, transcript_background_backoff_base_seconds
        )
        self._transcript_background_backoff_max_seconds = max(
            self._transcript_background_backoff_base_seconds,
            transcript_background_backoff_max_seconds,
        )
        self._transcript_background_ip_block_pause_seconds = max(
            60,
            transcript_background_ip_block_pause_seconds,
        )
        resolved_oauth_paths = resolve_oauth_paths(
            data_dir,
            token_override=oauth_token_path,
            secret_override=oauth_client_secret_path,
        )
        self._oauth_token_path, self._oauth_client_secret_path = resolved_oauth_paths
        self._supadata_api_key = _normalize_env_text(supadata_api_key)
        self._supadata_base_url = _normalize_supadata_base_url(supadata_base_url)
        self._supadata_transcript_mode = _normalize_supadata_transcript_mode(
            supadata_transcript_mode
        )
        self._supadata_http_timeout_seconds = max(1.0, supadata_http_timeout_seconds)
        self._supadata_poll_interval_seconds = max(0.2, supadata_poll_interval_seconds)
        self._supadata_poll_max_attempts = max(1, supadata_poll_max_attempts)
        self._youtube_transcript_api_fallback_last_query_at_in_memory: datetime | None = None

    @property
    def is_oauth_mode(self) -> bool:
        return True

    @property
    def supadata_configured(self) -> bool:
        return self._supadata_api_key is not None

    def _transcript_background_provider(self) -> str:
        if self._supadata_api_key is not None:
            return "supadata"
        return "youtube"

    def _build_oauth_client(self) -> Any:
        return _build_youtube_client(
            self._data_dir,
            token_path=self._oauth_token_path,
            secrets_path=self._oauth_client_secret_path,
        )

    def _fetch_video_snippet(self, video_id: str) -> _VideoSnippet:
        return _fetch_video_snippet(
            video_id,
            self._data_dir,
            token_path=self._oauth_token_path,
            secrets_path=self._oauth_client_secret_path,
        )

    def _filter_likes_videos_by_cutoff(
        self,
        videos: list[YouTubeVideo],
    ) -> tuple[list[YouTubeVideo], bool]:
        if not videos:
            return [], False

        filtered: list[YouTubeVideo] = []
        reached_cutoff = False
        for video in videos:
            liked_at = _parse_datetime_utc(video.liked_at or video.published_at)
            if liked_at is None:
                # Keep unparsable rows rather than silently dropping likes.
                filtered.append(video)
                continue
            if liked_at < self._likes_cutoff_datetime:
                reached_cutoff = True
                continue
            filtered.append(video)
        return filtered, reached_cutoff

    def _apply_likes_cache_scope(self, *, source: str) -> None:
        if self._cache_repository is None:
            return

        purged_likes = self._cache_repository.purge_likes_before(
            cutoff_liked_at=self._likes_cutoff_datetime
        )
        purged_transcripts, purged_sync_rows = (
            self._cache_repository.purge_transcript_rows_not_in_active_sources()
        )
        transitioned_watch_later = (
            self._cache_repository.transition_removed_not_liked_to_watched_for_likes()
        )
        if purged_likes or purged_transcripts or purged_sync_rows or transitioned_watch_later:
            LOGGER.info(
                (
                    "youtube likes scope_apply source=%s cutoff_date=%s "
                    "purged_likes=%s purged_transcripts=%s purged_sync_rows=%s "
                    "watch_later_transitioned=%s"
                ),
                source,
                self._likes_cutoff_date.isoformat(),
                purged_likes,
                purged_transcripts,
                purged_sync_rows,
                transitioned_watch_later,
            )

    def run_background_likes_sync(self) -> None:
        if not self._likes_background_sync_enabled or self._cache_repository is None:
            return

        if not self._background_sync_interval_elapsed():
            return

        likes_rows_before = self._cache_repository.count_likes()
        LOGGER.info(
            (
                "youtube likes background_sync start hot_pages=%s backfill_pages=%s "
                "page_size=%s cutoff_date=%s cache_rows=%s"
            ),
            self._likes_background_hot_pages,
            self._likes_background_backfill_pages_per_run,
            self._likes_background_page_size,
            self._likes_cutoff_date.isoformat(),
            likes_rows_before,
        )
        client = self._build_oauth_client()
        likes_playlist_id = _resolve_likes_playlist_id(client)

        hot_next_page_token: str | None = None
        total_units = 1  # channels.list in _resolve_likes_playlist_id
        upserted_rows = 0

        hot_pages_processed = 0
        backfill_pages_processed = 0

        for hot_page_index in range(self._likes_background_hot_pages):
            page_fetch = _list_liked_videos_page(
                client,
                likes_playlist_id=likes_playlist_id,
                page_size=self._likes_background_page_size,
                page_token=hot_next_page_token,
                enrich_metadata=False,
            )
            total_units += page_fetch.estimated_api_units
            hot_pages_processed += 1
            self._purge_members_only_videos(
                video_ids=page_fetch.excluded_members_only_video_ids,
                source="likes_background_hot_page",
            )
            scoped_videos, reached_cutoff = self._filter_likes_videos_by_cutoff(page_fetch.videos)
            if not scoped_videos:
                LOGGER.info(
                    "youtube likes background_sync hot_page=%s empty next_page_token=%s cutoff_reached=%s",
                    hot_page_index + 1,
                    bool(page_fetch.next_page_token),
                    reached_cutoff,
                )
                hot_next_page_token = None
                break

            scoped_videos, metadata_calls = self._enrich_videos_from_cache_then_api(
                client=client,
                videos=scoped_videos,
                enrich_metadata=True,
            )
            total_units += metadata_calls
            cached_rows = [_video_to_cached_like(video) for video in scoped_videos]
            self._cache_repository.upsert_likes(
                videos=cached_rows,
                max_items=None,
            )
            upserted_rows += len(cached_rows)
            LOGGER.info(
                "youtube likes background_sync hot_page=%s fetched=%s next_page_token=%s cutoff_reached=%s",
                hot_page_index + 1,
                len(cached_rows),
                bool(page_fetch.next_page_token),
                reached_cutoff,
            )
            if reached_cutoff:
                hot_next_page_token = None
                break

            hot_next_page_token = page_fetch.next_page_token
            if hot_next_page_token is None:
                break

        backfill_page_token = self._cache_repository.get_cache_state_value(
            LIKES_BACKGROUND_BACKFILL_NEXT_PAGE_TOKEN_KEY
        )
        if backfill_page_token is None:
            backfill_page_token = hot_next_page_token

        for backfill_page_index in range(self._likes_background_backfill_pages_per_run):
            if backfill_page_token is None:
                break

            page_fetch = _list_liked_videos_page(
                client,
                likes_playlist_id=likes_playlist_id,
                page_size=self._likes_background_page_size,
                page_token=backfill_page_token,
                enrich_metadata=False,
            )
            total_units += page_fetch.estimated_api_units
            backfill_pages_processed += 1
            self._purge_members_only_videos(
                video_ids=page_fetch.excluded_members_only_video_ids,
                source="likes_background_backfill_page",
            )
            scoped_videos, reached_cutoff = self._filter_likes_videos_by_cutoff(page_fetch.videos)
            if scoped_videos:
                scoped_videos, metadata_calls = self._enrich_videos_from_cache_then_api(
                    client=client,
                    videos=scoped_videos,
                    enrich_metadata=True,
                )
                total_units += metadata_calls
                cached_rows = [_video_to_cached_like(video) for video in scoped_videos]
                self._cache_repository.upsert_likes(
                    videos=cached_rows,
                    max_items=None,
                )
                upserted_rows += len(cached_rows)
                LOGGER.info(
                    "youtube likes background_sync backfill_page=%s fetched=%s next_page_token=%s cutoff_reached=%s",
                    backfill_page_index + 1,
                    len(cached_rows),
                    bool(page_fetch.next_page_token),
                    reached_cutoff,
                )
            else:
                LOGGER.info(
                    "youtube likes background_sync backfill_page=%s empty next_page_token=%s cutoff_reached=%s",
                    backfill_page_index + 1,
                    bool(page_fetch.next_page_token),
                    reached_cutoff,
                )

            if reached_cutoff:
                backfill_page_token = None
                break

            backfill_page_token = page_fetch.next_page_token
            if backfill_page_token is None:
                break

        if backfill_page_token is None:
            self._cache_repository.clear_cache_state_value(
                key=LIKES_BACKGROUND_BACKFILL_NEXT_PAGE_TOKEN_KEY
            )
        else:
            self._cache_repository.set_cache_state_value(
                key=LIKES_BACKGROUND_BACKFILL_NEXT_PAGE_TOKEN_KEY,
                value=backfill_page_token,
            )

        self._apply_likes_cache_scope(source="likes_background_sync")
        self._mark_background_sync_run()
        likes_rows_after = self._cache_repository.count_likes()
        LOGGER.info(
            (
                "youtube likes background_sync done upserted=%s units=%s hot_pages=%s "
                "backfill_pages=%s backfill_token_set=%s cache_rows_before=%s "
                "cache_rows_after=%s cutoff_date=%s"
            ),
            upserted_rows,
            total_units,
            hot_pages_processed,
            backfill_pages_processed,
            backfill_page_token is not None,
            likes_rows_before,
            likes_rows_after,
            self._likes_cutoff_date.isoformat(),
        )

    def run_background_watch_later_metadata_sync(
        self,
        *,
        force: bool = False,
        max_videos: int | None = None,
    ) -> int:
        if self._cache_repository is None:
            return 0
        if not force and not self._watch_later_metadata_sync_enabled:
            return 0
        if not force and not self._watch_later_metadata_sync_interval_elapsed():
            return 0

        batch_size = (
            self._watch_later_metadata_sync_batch_size if max_videos is None else max(1, max_videos)
        )
        scan_limit = max(batch_size, batch_size * 4)
        active_rows = self._cache_repository.list_watch_later(
            limit=scan_limit,
            statuses=(WATCH_LATER_STATUS_ACTIVE,),
        )
        candidates = [row for row in active_rows if _watch_later_row_needs_metadata(row)][
            :batch_size
        ]
        if not candidates:
            self._mark_watch_later_metadata_sync_run()
            return 0

        videos = [_cached_watch_later_to_video(row) for row in candidates]
        enriched_videos, metadata_calls = self._enrich_videos_from_cache_then_api(
            videos=videos,
            enrich_metadata=True,
        )
        candidates_by_id = {row.video_id: row for row in candidates}
        updated_rows = [
            _video_to_cached_watch_later(
                video=video,
                existing=candidates_by_id[video.video_id],
            )
            for video in enriched_videos
        ]
        self._cache_repository.upsert_watch_later_videos(videos=updated_rows)
        self._mark_watch_later_metadata_sync_run()
        LOGGER.info(
            (
                "youtube watch_later metadata_sync done candidates=%s updated=%s "
                "metadata_api_units=%s"
            ),
            len(candidates),
            len(updated_rows),
            metadata_calls,
        )
        return metadata_calls

    def push_watch_later_snapshot(
        self,
        *,
        video_ids: list[str],
        source_client: str,
        generated_at_utc: str | None,
        videos: list[dict[str, Any]] | None = None,
    ) -> dict[str, object]:
        if self._cache_repository is None:
            raise YouTubeServiceError("YouTube cache repository is required for watch later ingest")

        ingest_result = self._cache_repository.apply_watch_later_snapshot(
            video_ids=video_ids,
            generated_at_utc=generated_at_utc,
            source_client=source_client.strip() or "unknown",
        )
        transitioned = self._cache_repository.transition_removed_not_liked_to_watched_for_likes()
        ingest_result["watch_later_transitioned_from_likes"] = transitioned

        snapshot_videos = videos or []
        if snapshot_videos:
            self._upsert_watch_later_snapshot_details(snapshot_videos)
            ingest_result["videos_with_snapshot_details"] = len(snapshot_videos)
        else:
            ingest_result["videos_with_snapshot_details"] = 0

        metadata_api_units = self.run_background_watch_later_metadata_sync(force=True)
        ingest_result["metadata_api_units"] = metadata_api_units
        return ingest_result

    def _upsert_watch_later_snapshot_details(self, videos: list[dict[str, Any]]) -> None:
        if self._cache_repository is None or not videos:
            return

        now_iso = datetime.now(UTC).isoformat()
        by_video_id: dict[str, dict[str, Any]] = {}
        for payload in videos:
            raw_video_id = payload.get("video_id")
            if not isinstance(raw_video_id, str):
                continue
            video_id = raw_video_id.strip()
            if not video_id:
                continue
            by_video_id[video_id] = payload
        if not by_video_id:
            return

        ordered_ids = list(by_video_id.keys())
        existing_by_id = self._cache_repository.get_watch_later_by_video_ids(video_ids=ordered_ids)
        likes_by_id = self._cache_repository.get_likes_by_video_ids(video_ids=ordered_ids)

        upsert_rows: list[CachedWatchLaterVideo] = []
        for video_id in ordered_ids:
            payload = by_video_id[video_id]
            existing = existing_by_id.get(video_id)
            from_likes = likes_by_id.get(video_id)
            tags = _extract_string_list(payload.get("tags"))
            if not tags:
                tags = (
                    existing.tags
                    if existing is not None
                    else (from_likes.tags if from_likes is not None else ())
                )
            topic_categories = _extract_string_list(payload.get("topic_categories"))
            if not topic_categories:
                topic_categories = (
                    existing.topic_categories
                    if existing is not None
                    else (from_likes.topic_categories if from_likes is not None else ())
                )
            thumbnails = _coerce_thumbnail_map(payload.get("thumbnails"))
            if not thumbnails:
                thumbnails = (
                    dict(existing.thumbnails)
                    if existing is not None
                    else (dict(from_likes.thumbnails) if from_likes is not None else {})
                )
            watch_later_added_at = _coerce_nonempty_string(payload.get("watch_later_added_at"))
            first_seen_at = _coerce_nonempty_string(payload.get("first_seen_at"))
            upsert_rows.append(
                CachedWatchLaterVideo(
                    video_id=video_id,
                    title=(
                        _coerce_nonempty_string(payload.get("title"))
                        or (existing.title if existing is not None else None)
                        or (from_likes.title if from_likes is not None else None)
                        or video_id
                    ),
                    watch_later_added_at=(
                        watch_later_added_at
                        or (existing.watch_later_added_at if existing is not None else now_iso)
                    ),
                    first_seen_at=(
                        first_seen_at
                        or (existing.first_seen_at if existing is not None else now_iso)
                    ),
                    last_seen_at=(existing.last_seen_at if existing is not None else now_iso),
                    status=(existing.status if existing is not None else WATCH_LATER_STATUS_ACTIVE),
                    removed_at=(existing.removed_at if existing is not None else None),
                    snapshot_position=(
                        _coerce_int(payload.get("snapshot_position"))
                        or (existing.snapshot_position if existing is not None else None)
                    ),
                    video_published_at=(
                        _coerce_nonempty_string(payload.get("video_published_at"))
                        or (existing.video_published_at if existing is not None else None)
                        or (from_likes.video_published_at if from_likes is not None else None)
                    ),
                    description=(
                        _coerce_nonempty_string(payload.get("description"))
                        or (existing.description if existing is not None else None)
                        or (from_likes.description if from_likes is not None else None)
                    ),
                    channel_id=(
                        _coerce_nonempty_string(payload.get("channel_id"))
                        or (existing.channel_id if existing is not None else None)
                        or (from_likes.channel_id if from_likes is not None else None)
                    ),
                    channel_title=(
                        _coerce_nonempty_string(payload.get("channel_title"))
                        or (existing.channel_title if existing is not None else None)
                        or (from_likes.channel_title if from_likes is not None else None)
                    ),
                    duration_seconds=(
                        _coerce_int(payload.get("duration_seconds"))
                        or (existing.duration_seconds if existing is not None else None)
                        or (from_likes.duration_seconds if from_likes is not None else None)
                    ),
                    category_id=(
                        _coerce_nonempty_string(payload.get("category_id"))
                        or (existing.category_id if existing is not None else None)
                        or (from_likes.category_id if from_likes is not None else None)
                    ),
                    default_language=(
                        _coerce_nonempty_string(payload.get("default_language"))
                        or (existing.default_language if existing is not None else None)
                        or (from_likes.default_language if from_likes is not None else None)
                    ),
                    default_audio_language=(
                        _coerce_nonempty_string(payload.get("default_audio_language"))
                        or (existing.default_audio_language if existing is not None else None)
                        or (from_likes.default_audio_language if from_likes is not None else None)
                    ),
                    caption_available=(
                        _coerce_bool(payload.get("caption_available"))
                        if payload.get("caption_available") is not None
                        else (
                            existing.caption_available
                            if existing is not None
                            else (from_likes.caption_available if from_likes is not None else None)
                        )
                    ),
                    privacy_status=(
                        _coerce_nonempty_string(payload.get("privacy_status"))
                        or (existing.privacy_status if existing is not None else None)
                        or (from_likes.privacy_status if from_likes is not None else None)
                    ),
                    licensed_content=(
                        _coerce_bool(payload.get("licensed_content"))
                        if payload.get("licensed_content") is not None
                        else (
                            existing.licensed_content
                            if existing is not None
                            else (from_likes.licensed_content if from_likes is not None else None)
                        )
                    ),
                    made_for_kids=(
                        _coerce_bool(payload.get("made_for_kids"))
                        if payload.get("made_for_kids") is not None
                        else (
                            existing.made_for_kids
                            if existing is not None
                            else (from_likes.made_for_kids if from_likes is not None else None)
                        )
                    ),
                    live_broadcast_content=(
                        _coerce_nonempty_string(payload.get("live_broadcast_content"))
                        or (existing.live_broadcast_content if existing is not None else None)
                        or (from_likes.live_broadcast_content if from_likes is not None else None)
                    ),
                    definition=(
                        _coerce_nonempty_string(payload.get("definition"))
                        or (existing.definition if existing is not None else None)
                        or (from_likes.definition if from_likes is not None else None)
                    ),
                    dimension=(
                        _coerce_nonempty_string(payload.get("dimension"))
                        or (existing.dimension if existing is not None else None)
                        or (from_likes.dimension if from_likes is not None else None)
                    ),
                    thumbnails=thumbnails,
                    topic_categories=topic_categories,
                    statistics_view_count=(
                        _coerce_int(payload.get("statistics_view_count"))
                        or (existing.statistics_view_count if existing is not None else None)
                        or (from_likes.statistics_view_count if from_likes is not None else None)
                    ),
                    statistics_like_count=(
                        _coerce_int(payload.get("statistics_like_count"))
                        or (existing.statistics_like_count if existing is not None else None)
                        or (from_likes.statistics_like_count if from_likes is not None else None)
                    ),
                    statistics_comment_count=(
                        _coerce_int(payload.get("statistics_comment_count"))
                        or (existing.statistics_comment_count if existing is not None else None)
                        or (from_likes.statistics_comment_count if from_likes is not None else None)
                    ),
                    statistics_fetched_at=(
                        _coerce_nonempty_string(payload.get("statistics_fetched_at"))
                        or (existing.statistics_fetched_at if existing is not None else None)
                        or (from_likes.statistics_fetched_at if from_likes is not None else None)
                    ),
                    tags=tags,
                )
            )
        if upsert_rows:
            self._cache_repository.upsert_watch_later_videos(videos=upsert_rows)

    def _watch_later_metadata_sync_interval_elapsed(self) -> bool:
        if self._cache_repository is None:
            return False
        if self._watch_later_metadata_sync_min_interval_seconds <= 0:
            return True

        raw_last_run = self._cache_repository.get_cache_state_value(
            WATCH_LATER_METADATA_BACKGROUND_LAST_RUN_AT_KEY
        )
        if raw_last_run is None:
            return True
        parsed = _parse_datetime_utc(raw_last_run)
        if parsed is None:
            return True
        return datetime.now(UTC) - parsed >= timedelta(
            seconds=self._watch_later_metadata_sync_min_interval_seconds
        )

    def _mark_watch_later_metadata_sync_run(self) -> None:
        if self._cache_repository is None:
            return
        self._cache_repository.set_cache_state_value(
            key=WATCH_LATER_METADATA_BACKGROUND_LAST_RUN_AT_KEY,
            value=datetime.now(UTC).isoformat(),
        )

    def _enrich_videos_from_cache_then_api(
        self,
        *,
        videos: list[YouTubeVideo],
        enrich_metadata: bool,
        client: Any | None = None,
    ) -> tuple[list[YouTubeVideo], int]:
        if not videos:
            return [], 0

        hydrated_videos = list(videos)
        if self._cache_repository is not None:
            video_ids = [video.video_id for video in hydrated_videos]
            likes_by_id = self._cache_repository.get_likes_by_video_ids(video_ids=video_ids)
            watch_later_by_id = self._cache_repository.get_watch_later_by_video_ids(
                video_ids=video_ids
            )
            hydrated: list[YouTubeVideo] = []
            for video in hydrated_videos:
                enriched_video = video
                like = likes_by_id.get(video.video_id)
                if like is not None:
                    enriched_video = _merge_video_metadata(
                        enriched_video,
                        _metadata_from_cached_like(like),
                    )
                watch_later = watch_later_by_id.get(video.video_id)
                if watch_later is not None:
                    enriched_video = _merge_video_metadata(
                        enriched_video,
                        _metadata_from_cached_watch_later(watch_later),
                    )
                hydrated.append(enriched_video)
            hydrated_videos = hydrated

        if not enrich_metadata:
            return hydrated_videos, 0
        videos_needing_api_metadata = [
            video for video in hydrated_videos if _video_needs_metadata_refresh(video)
        ]
        if not videos_needing_api_metadata:
            return hydrated_videos, 0
        resolved_client = client if client is not None else self._build_oauth_client()
        fetched_videos, metadata_calls = _enrich_liked_video_metadata(
            resolved_client,
            videos_needing_api_metadata,
        )
        fetched_by_id = {video.video_id: video for video in fetched_videos}
        merged: list[YouTubeVideo] = []
        for video in hydrated_videos:
            fetched = fetched_by_id.get(video.video_id)
            if fetched is None:
                merged.append(video)
                continue
            merged.append(_merge_video_metadata(video, _video_to_metadata(fetched), overwrite=True))
        return merged, metadata_calls

    def _background_sync_interval_elapsed(self) -> bool:
        if self._cache_repository is None:
            return False
        if self._likes_background_min_interval_seconds <= 0:
            return True

        raw_last_run = self._cache_repository.get_cache_state_value(
            LIKES_BACKGROUND_LAST_RUN_AT_KEY
        )
        if raw_last_run is None:
            return True

        try:
            parsed = datetime.fromisoformat(raw_last_run)
        except ValueError:
            return True

        parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

        return datetime.now(UTC) - parsed >= timedelta(
            seconds=self._likes_background_min_interval_seconds
        )

    def _mark_background_sync_run(self) -> None:
        if self._cache_repository is None:
            return
        now_iso = datetime.now(UTC).isoformat()
        self._cache_repository.set_cache_state_value(
            key=LIKES_BACKGROUND_LAST_RUN_AT_KEY,
            value=now_iso,
        )

    def _likes_recent_probe_pause_until(self, now: datetime) -> datetime | None:
        if self._cache_repository is None:
            return None

        raw_value = self._cache_repository.get_cache_state_value(
            LIKES_RECENT_PROBE_RATE_LIMIT_PAUSED_UNTIL_KEY
        )
        parsed = _parse_datetime_utc(raw_value)
        if parsed is None:
            return None
        if parsed <= now:
            self._cache_repository.clear_cache_state_value(
                key=LIKES_RECENT_PROBE_RATE_LIMIT_PAUSED_UNTIL_KEY
            )
            return None
        return parsed

    def _set_likes_recent_probe_pause_until(self, pause_until: datetime) -> None:
        if self._cache_repository is None:
            return
        self._cache_repository.set_cache_state_value(
            key=LIKES_RECENT_PROBE_RATE_LIMIT_PAUSED_UNTIL_KEY,
            value=pause_until.astimezone(UTC).isoformat(),
        )

    def _current_likes_recent_probe_rate_limit_streak(self) -> int:
        if self._cache_repository is None:
            return 0

        raw_streak = self._cache_repository.get_cache_state_value(
            LIKES_RECENT_PROBE_RATE_LIMIT_STREAK_KEY
        )
        if raw_streak is None:
            return 0
        try:
            parsed = int(raw_streak)
        except ValueError:
            return 0
        return max(0, parsed)

    def _increment_likes_recent_probe_rate_limit_streak(self) -> int:
        if self._cache_repository is None:
            return 1

        updated = self._current_likes_recent_probe_rate_limit_streak() + 1
        self._cache_repository.set_cache_state_value(
            key=LIKES_RECENT_PROBE_RATE_LIMIT_STREAK_KEY,
            value=str(updated),
        )
        return updated

    def _clear_likes_recent_probe_rate_limit_streak(self) -> None:
        if self._cache_repository is None:
            return
        self._cache_repository.clear_cache_state_value(key=LIKES_RECENT_PROBE_RATE_LIMIT_STREAK_KEY)

    def _compute_likes_recent_probe_rate_limit_backoff_seconds(
        self,
        *,
        streak: int,
        retry_after_hint: int | None,
    ) -> int:
        clamped_streak = max(1, streak)
        exponential = LIKES_RECENT_PROBE_RATE_LIMIT_BASE_SECONDS * (2 ** (clamped_streak - 1))
        computed = min(LIKES_RECENT_PROBE_RATE_LIMIT_MAX_SECONDS, exponential)
        if retry_after_hint is not None:
            return max(computed, retry_after_hint)
        return computed

    def _probe_recent_likes_cache(
        self,
        *,
        recent_probe_pages: int,
        enrich_metadata: bool,
    ) -> tuple[int, int]:
        if self._cache_repository is None:
            return 0, 0

        now = datetime.now(UTC)
        pause_until = self._likes_recent_probe_pause_until(now)
        if pause_until is not None:
            remaining_seconds = max(1, int((pause_until - now).total_seconds()))
            raise YouTubeRateLimitedError(
                (
                    "YouTube recent-likes probe is currently paused because of rate limiting. "
                    f"Retry after about {remaining_seconds} seconds."
                ),
                retry_after_seconds=remaining_seconds,
                scope="youtube_data_api_recent_probe",
            )

        try:
            client = self._build_oauth_client()
            likes_playlist_id = _resolve_likes_playlist_id(client)

            pages_to_fetch = max(1, min(3, recent_probe_pages))
            estimated_units = 1  # channels.list in _resolve_likes_playlist_id
            pages_used = 0
            next_page_token: str | None = None
            fetched_videos: list[YouTubeVideo] = []

            for _ in range(pages_to_fetch):
                page_fetch = _list_liked_videos_page(
                    client,
                    likes_playlist_id=likes_playlist_id,
                    page_size=self._likes_background_page_size,
                    page_token=next_page_token,
                    enrich_metadata=False,
                )
                estimated_units += page_fetch.estimated_api_units
                pages_used += 1
                scoped_videos, reached_cutoff = self._filter_likes_videos_by_cutoff(
                    page_fetch.videos
                )
                scoped_videos, metadata_calls = self._enrich_videos_from_cache_then_api(
                    client=client,
                    videos=scoped_videos,
                    enrich_metadata=enrich_metadata,
                )
                estimated_units += metadata_calls
                fetched_videos.extend(scoped_videos)
                next_page_token = page_fetch.next_page_token
                if next_page_token is None or reached_cutoff:
                    break

            if fetched_videos:
                cache_rows = [_video_to_cached_like(video) for video in fetched_videos]
                self._cache_repository.upsert_likes(
                    videos=cache_rows,
                    max_items=None,
                )
            self._apply_likes_cache_scope(source="likes_recent_probe")

            self._clear_likes_recent_probe_rate_limit_streak()
            LOGGER.info(
                "youtube likes recent_probe pages_used=%s fetched_videos=%s units=%s",
                pages_used,
                len(fetched_videos),
                estimated_units,
            )
            return estimated_units, pages_used
        except Exception as exc:
            if not _is_youtube_data_api_rate_limit_error(exc):
                raise

            streak = self._increment_likes_recent_probe_rate_limit_streak()
            retry_after_hint = _extract_retry_after_seconds_from_error(exc)
            pause_seconds = self._compute_likes_recent_probe_rate_limit_backoff_seconds(
                streak=streak,
                retry_after_hint=retry_after_hint,
            )
            pause_until = now + timedelta(seconds=pause_seconds)
            self._set_likes_recent_probe_pause_until(pause_until)
            LOGGER.warning(
                (
                    "youtube likes recent_probe rate_limited streak=%s "
                    "retry_after_seconds=%s hint_seconds=%s"
                ),
                streak,
                pause_seconds,
                retry_after_hint,
            )
            raise YouTubeRateLimitedError(
                (
                    "YouTube Data API is currently rate-limiting recent-likes refresh requests. "
                    f"Retry after about {pause_seconds} seconds."
                ),
                retry_after_seconds=pause_seconds,
                scope="youtube_data_api_recent_probe",
            ) from exc

    def run_background_transcript_sync(self) -> None:
        if not self._transcript_background_sync_enabled or self._cache_repository is None:
            return

        if not self._transcript_background_interval_elapsed():
            return

        now = datetime.now(UTC)
        pause_until = self._transcript_global_pause_until(now)
        provider = self._transcript_background_provider()
        if pause_until is not None:
            self._mark_transcript_background_run()
            remaining_seconds = max(0, int((pause_until - now).total_seconds()))
            ip_block_streak = self._current_transcript_ip_block_streak()
            LOGGER.warning(
                (
                    "youtube transcript background_sync skip reason=ip_block_pause "
                    "provider=%s remaining_seconds=%s ip_block_streak=%s"
                ),
                provider,
                remaining_seconds,
                ip_block_streak,
            )
            return

        likes_rows = self._cache_repository.count_likes()
        transcript_rows_before = self._cache_repository.count_transcripts()
        coverage_before = _percent_progress(transcript_rows_before, likes_rows)
        status_counts_before = self._cache_repository.count_transcript_sync_state_by_status()

        candidate = self._cache_repository.get_next_transcript_candidate(not_before=now)
        if candidate is None:
            self._mark_transcript_background_run()
            return

        LOGGER.info(
            (
                "youtube transcript background_sync start video_id=%s provider=%s recency_at=%s "
                "likes_rows=%s transcript_rows=%s coverage=%s%% done=%s retry_wait=%s"
            ),
            candidate.video_id,
            provider,
            candidate.recency_at,
            likes_rows,
            transcript_rows_before,
            coverage_before,
            status_counts_before.get("done", 0),
            status_counts_before.get("retry_wait", 0),
        )
        try:
            transcript_result = self.get_transcript_with_metadata(candidate.video_id)
        except TranscriptExcludedVideoError as exc:
            self._cache_repository.purge_youtube_video(video_id=candidate.video_id)
            self._mark_transcript_background_run()
            status_counts_after = self._cache_repository.count_transcript_sync_state_by_status()
            LOGGER.warning(
                (
                    "youtube transcript background_sync exclude video_id=%s provider=%s "
                    "reason=members_only inferred_from=%s done=%s retry_wait=%s"
                ),
                candidate.video_id,
                provider,
                _summarize_exception_message(exc),
                status_counts_after.get("done", 0),
                status_counts_after.get("retry_wait", 0),
            )
            return
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = _summarize_exception_message(exc)
            ip_blocked = _is_transcript_ip_block_error(exc)
            attempts = (
                self._cache_repository.get_transcript_sync_attempts(video_id=candidate.video_id) + 1
            )
            backoff_seconds = self._compute_transcript_backoff_seconds(attempts)
            ip_block_streak: int | None = None
            if ip_blocked:
                ip_block_streak = self._increment_transcript_ip_block_streak()
                ip_block_pause_seconds = self._compute_transcript_ip_block_pause_seconds(
                    ip_block_streak
                )
                backoff_seconds = max(
                    backoff_seconds,
                    ip_block_pause_seconds,
                )
            next_attempt_at = now + timedelta(seconds=backoff_seconds)
            if ip_blocked:
                self._set_transcript_global_pause_until(next_attempt_at)
            self._cache_repository.mark_transcript_sync_failure(
                video_id=candidate.video_id,
                attempts=attempts,
                next_attempt_at=next_attempt_at,
                error=f"{error_type}: {error_message}",
            )
            self._mark_transcript_background_run()
            status_counts_after = self._cache_repository.count_transcript_sync_state_by_status()
            LOGGER.warning(
                (
                    "youtube transcript background_sync failed video_id=%s attempts=%s "
                    "provider=%s backoff_seconds=%s ip_blocked=%s ip_block_streak=%s "
                    "error_type=%s error=%s done=%s retry_wait=%s"
                ),
                candidate.video_id,
                attempts,
                provider,
                backoff_seconds,
                ip_blocked,
                ip_block_streak,
                error_type,
                error_message,
                status_counts_after.get("done", 0),
                status_counts_after.get("retry_wait", 0),
                exc_info=True,
            )
            return

        self._cache_repository.mark_transcript_sync_success(video_id=candidate.video_id)
        self._clear_transcript_ip_block_streak()
        self._mark_transcript_background_run()
        transcript_rows_after = self._cache_repository.count_transcripts()
        coverage_after = _percent_progress(transcript_rows_after, likes_rows)
        status_counts_after = self._cache_repository.count_transcript_sync_state_by_status()
        LOGGER.info(
            (
                "youtube transcript background_sync done video_id=%s provider=%s "
                "cache_hit=%s source=%s provider_request_id=%s "
                "transcript_rows_before=%s transcript_rows_after=%s coverage=%s%% "
                "done=%s retry_wait=%s"
            ),
            candidate.video_id,
            provider,
            transcript_result.cache_hit,
            transcript_result.transcript.source,
            transcript_result.provider_request_id,
            transcript_rows_before,
            transcript_rows_after,
            coverage_after,
            status_counts_after.get("done", 0),
            status_counts_after.get("retry_wait", 0),
        )

    def _purge_members_only_videos(self, *, video_ids: tuple[str, ...], source: str) -> None:
        if self._cache_repository is None or not video_ids:
            return
        for video_id in video_ids:
            self._cache_repository.purge_youtube_video(video_id=video_id)
            LOGGER.info(
                "youtube likes exclude video_id=%s reason=members_only source=%s",
                video_id,
                source,
            )

    def _transcript_background_interval_elapsed(self) -> bool:
        if self._cache_repository is None:
            return False
        if self._transcript_background_min_interval_seconds <= 0:
            return True

        raw_last_run = self._cache_repository.get_cache_state_value(
            TRANSCRIPTS_BACKGROUND_LAST_RUN_AT_KEY
        )
        if raw_last_run is None:
            return True

        try:
            parsed = datetime.fromisoformat(raw_last_run)
        except ValueError:
            return True

        parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        return datetime.now(UTC) - parsed >= timedelta(
            seconds=self._transcript_background_min_interval_seconds
        )

    def _mark_transcript_background_run(self) -> None:
        if self._cache_repository is None:
            return
        now_iso = datetime.now(UTC).isoformat()
        self._cache_repository.set_cache_state_value(
            key=TRANSCRIPTS_BACKGROUND_LAST_RUN_AT_KEY,
            value=now_iso,
        )

    def _transcript_global_pause_until(self, now: datetime) -> datetime | None:
        if self._cache_repository is None:
            return None

        raw_value = self._cache_repository.get_cache_state_value(
            TRANSCRIPTS_BACKGROUND_IP_BLOCK_PAUSED_UNTIL_KEY
        )
        parsed = _parse_datetime_utc(raw_value)
        if parsed is None:
            return None
        if parsed <= now:
            self._cache_repository.clear_cache_state_value(
                key=TRANSCRIPTS_BACKGROUND_IP_BLOCK_PAUSED_UNTIL_KEY
            )
            return None
        return parsed

    def _set_transcript_global_pause_until(self, pause_until: datetime) -> None:
        if self._cache_repository is None:
            return
        self._cache_repository.set_cache_state_value(
            key=TRANSCRIPTS_BACKGROUND_IP_BLOCK_PAUSED_UNTIL_KEY,
            value=pause_until.astimezone(UTC).isoformat(),
        )

    def _current_transcript_ip_block_streak(self) -> int:
        if self._cache_repository is None:
            return 0

        raw_streak = self._cache_repository.get_cache_state_value(
            TRANSCRIPTS_BACKGROUND_IP_BLOCK_STREAK_KEY
        )
        if raw_streak is None:
            return 0
        try:
            parsed = int(raw_streak)
        except ValueError:
            return 0
        return max(0, parsed)

    def _increment_transcript_ip_block_streak(self) -> int:
        if self._cache_repository is None:
            return 1

        updated = self._current_transcript_ip_block_streak() + 1
        self._cache_repository.set_cache_state_value(
            key=TRANSCRIPTS_BACKGROUND_IP_BLOCK_STREAK_KEY,
            value=str(updated),
        )
        return updated

    def _clear_transcript_ip_block_streak(self) -> None:
        if self._cache_repository is None:
            return
        self._cache_repository.clear_cache_state_value(
            key=TRANSCRIPTS_BACKGROUND_IP_BLOCK_STREAK_KEY
        )

    def _compute_transcript_ip_block_pause_seconds(self, streak: int) -> int:
        clamped_streak = max(1, streak)
        pause_seconds = self._transcript_background_ip_block_pause_seconds * (
            2 ** (clamped_streak - 1)
        )
        return min(self._transcript_background_backoff_max_seconds, pause_seconds)

    def _compute_transcript_backoff_seconds(self, attempts: int) -> int:
        exponent = max(0, attempts - 1)
        backoff = self._transcript_background_backoff_base_seconds * (2**exponent)
        return min(self._transcript_background_backoff_max_seconds, backoff)

    def list_recent(self, limit: int, query: str | None = None) -> list[YouTubeVideo]:
        return self.list_recent_with_metadata(limit=limit, query=query).videos

    def list_watch_later_cached_only_with_metadata(
        self,
        *,
        limit: int,
        query: str | None = None,
        cursor: int = 0,
        include_removed: bool = False,
    ) -> YouTubeListRecentResult:
        normalized_limit = max(1, min(100, limit))
        normalized_cursor = max(0, cursor)
        if self._cache_repository is None:
            raise YouTubeServiceError(
                "YouTube cache repository is required for cached watch later flow"
            )

        statuses = (
            (WATCH_LATER_STATUS_ACTIVE,)
            if not include_removed
            else (
                WATCH_LATER_STATUS_ACTIVE,
                WATCH_LATER_STATUS_REMOVED_WATCHED,
                WATCH_LATER_STATUS_REMOVED_NOT_LIKED,
            )
        )
        cached_rows = self._cache_repository.list_watch_later(
            limit=max(self._likes_cache_max_items, normalized_limit + normalized_cursor),
            statuses=statuses,
        )
        videos = [_cached_watch_later_to_video(row) for row in cached_rows]
        filtered = videos if query is None else _filter_videos_by_query(videos, query)
        total_matches = len(filtered)
        page_start = min(normalized_cursor, total_matches)
        page_end = min(total_matches, page_start + normalized_limit)
        page = filtered[page_start:page_end]
        has_more = page_end < total_matches
        next_cursor = page_end if has_more else None

        return YouTubeListRecentResult(
            videos=page,
            estimated_api_units=0,
            cache_hit=bool(videos),
            refreshed=False,
            cache_miss=query is not None and not filtered,
            recent_probe_applied=False,
            recent_probe_pages_used=0,
            cursor=page_start,
            next_cursor=next_cursor,
            has_more=has_more,
            total_matches=total_matches,
            applied_limit=normalized_limit,
        )

    def search_watch_later_content_with_metadata(
        self,
        *,
        query: str,
        window_days: int | None,
        limit: int,
        include_removed: bool = False,
    ) -> YouTubeRecentContentSearchResult:
        normalized_limit = max(1, min(25, limit))
        normalized_window_days = None if window_days is None else max(1, min(30, window_days))
        normalized_query = query.strip()
        if not normalized_query:
            raise YouTubeServiceError("payload.query is required")
        if self._cache_repository is None:
            raise YouTubeServiceError(
                "YouTube cache repository is required for cached watch later flow"
            )

        cutoff = (
            None
            if normalized_window_days is None
            else datetime.now(UTC) - timedelta(days=normalized_window_days)
        )
        statuses = (
            (WATCH_LATER_STATUS_ACTIVE,)
            if not include_removed
            else (
                WATCH_LATER_STATUS_ACTIVE,
                WATCH_LATER_STATUS_REMOVED_WATCHED,
                WATCH_LATER_STATUS_REMOVED_NOT_LIKED,
            )
        )
        cached_rows = self._cache_repository.list_watch_later(
            limit=self._likes_cache_max_items,
            statuses=statuses,
        )
        videos: list[YouTubeVideo] = []
        for row in cached_rows:
            recency_raw = row.watch_later_added_at or row.last_seen_at or row.first_seen_at
            recency = _parse_datetime_utc(recency_raw)
            if recency is None:
                continue
            if cutoff is not None and recency < cutoff:
                continue
            videos.append(_cached_watch_later_to_video(row))

        transcript_texts = self._cache_repository.get_cached_transcript_texts(
            video_ids=[video.video_id for video in videos]
        )
        matches = _search_recent_content_matches(
            query=normalized_query,
            videos=videos,
            transcript_texts=transcript_texts,
        )
        transcript_count = len(transcript_texts)
        return YouTubeRecentContentSearchResult(
            matches=matches[:normalized_limit],
            recent_videos_count=len(videos),
            transcripts_available_count=transcript_count,
            transcript_coverage_percent=_percent_progress(transcript_count, len(videos)),
            estimated_api_units=0,
            cache_miss=not matches,
            recent_probe_applied=False,
            recent_probe_pages_used=0,
        )

    def recommend_watch_later_video_with_metadata(
        self,
        *,
        query: str | None,
        target_duration_minutes: int | None,
        duration_tolerance_minutes: int,
        include_removed: bool = False,
    ) -> YouTubeWatchLaterRecommendationResult:
        if self._cache_repository is None:
            raise YouTubeServiceError(
                "YouTube cache repository is required for cached watch later flow"
            )
        statuses = (
            (WATCH_LATER_STATUS_ACTIVE,)
            if not include_removed
            else (
                WATCH_LATER_STATUS_ACTIVE,
                WATCH_LATER_STATUS_REMOVED_WATCHED,
                WATCH_LATER_STATUS_REMOVED_NOT_LIKED,
            )
        )
        cached_rows = self._cache_repository.list_watch_later(
            limit=self._likes_cache_max_items,
            statuses=statuses,
        )
        candidates = [_cached_watch_later_to_video(row) for row in cached_rows]
        if not candidates:
            return YouTubeWatchLaterRecommendationResult(
                video=None,
                score=0,
                reason="no_watch_later_candidates",
            )

        normalized_query = query.strip() if isinstance(query, str) else ""
        score_by_video_id: dict[str, int] = {}
        if normalized_query:
            transcripts = self._cache_repository.get_cached_transcript_texts(
                video_ids=[video.video_id for video in candidates]
            )
            matches = _search_recent_content_matches(
                query=normalized_query,
                videos=candidates,
                transcript_texts=transcripts,
            )
            if matches:
                match_ids = {match.video.video_id for match in matches}
                candidates = [video for video in candidates if video.video_id in match_ids]
                score_by_video_id = {match.video.video_id: match.score for match in matches}
            else:
                candidates = _filter_videos_by_query(candidates, normalized_query)
            if not candidates:
                return YouTubeWatchLaterRecommendationResult(
                    video=None,
                    score=0,
                    reason="no_query_match",
                )

        target_seconds = (
            None if target_duration_minutes is None else max(1, target_duration_minutes) * 60
        )
        tolerance_seconds = max(0, duration_tolerance_minutes) * 60

        def _rank(video: YouTubeVideo) -> tuple[int, int, int]:
            score = score_by_video_id.get(video.video_id, 0)
            if target_seconds is None:
                return (0, -score, 0)
            duration_seconds = video.duration_seconds
            if duration_seconds is None:
                return (2, -score, 999_999)
            distance = abs(duration_seconds - target_seconds)
            in_tolerance = 0 if distance <= tolerance_seconds else 1
            return (in_tolerance, -score, distance)

        ranked = sorted(candidates, key=_rank)
        selected = ranked[0]
        selected_score = score_by_video_id.get(selected.video_id, 0)
        if target_seconds is None:
            reason = "best_query_match" if normalized_query else "most_recent_watch_later"
        else:
            duration_seconds = selected.duration_seconds
            if duration_seconds is None:
                reason = "best_query_match_missing_duration"
            elif abs(duration_seconds - target_seconds) <= tolerance_seconds:
                reason = "duration_within_tolerance"
            else:
                reason = "closest_duration_available"
        return YouTubeWatchLaterRecommendationResult(
            video=selected,
            score=selected_score,
            reason=reason,
        )

    def search_recent_content_with_metadata(
        self,
        *,
        query: str,
        window_days: int | None,
        limit: int,
        probe_recent_on_miss: bool,
        recent_probe_pages: int,
    ) -> YouTubeRecentContentSearchResult:
        normalized_limit = max(1, min(25, limit))
        normalized_window_days = None if window_days is None else max(1, min(30, window_days))
        normalized_query = query.strip()
        if not normalized_query:
            raise YouTubeServiceError("payload.query is required")

        cutoff = (
            None
            if normalized_window_days is None
            else datetime.now(UTC) - timedelta(days=normalized_window_days)
        )
        estimated_api_units = 0
        recent_probe_applied = False
        recent_probe_pages_used = 0

        if self._cache_repository is None:
            raise YouTubeServiceError("YouTube cache repository is required for cached likes flow")

        matches, recent_videos, transcript_texts = self._search_recent_cache_content(
            query=normalized_query,
            cutoff=cutoff,
        )
        cache_miss = not matches
        if cache_miss and probe_recent_on_miss:
            probe_units, pages_used = self._probe_recent_likes_cache(
                recent_probe_pages=recent_probe_pages,
                enrich_metadata=True,
            )
            estimated_api_units += probe_units
            recent_probe_applied = pages_used > 0
            recent_probe_pages_used = pages_used
            matches, recent_videos, transcript_texts = self._search_recent_cache_content(
                query=normalized_query,
                cutoff=cutoff,
            )
            cache_miss = not matches

        transcript_count = len(transcript_texts)
        window_log_value: int | str = (
            "all" if normalized_window_days is None else normalized_window_days
        )
        LOGGER.info(
            (
                "youtube recent_content_search query=%s window_days=%s matches=%s "
                "recent_videos=%s transcripts_available=%s cache_miss=%s probe_applied=%s "
                "probe_pages=%s"
            ),
            normalized_query,
            window_log_value,
            len(matches),
            len(recent_videos),
            transcript_count,
            cache_miss,
            recent_probe_applied,
            recent_probe_pages_used,
        )
        return YouTubeRecentContentSearchResult(
            matches=matches[:normalized_limit],
            recent_videos_count=len(recent_videos),
            transcripts_available_count=transcript_count,
            transcript_coverage_percent=_percent_progress(transcript_count, len(recent_videos)),
            estimated_api_units=estimated_api_units,
            cache_miss=cache_miss,
            recent_probe_applied=recent_probe_applied,
            recent_probe_pages_used=recent_probe_pages_used,
        )

    def _search_recent_cache_content(
        self,
        *,
        query: str,
        cutoff: datetime | None,
    ) -> tuple[list[YouTubeRecentContentMatch], list[YouTubeVideo], dict[str, str]]:
        if self._cache_repository is None:
            return [], [], {}

        cached_rows = self._cache_repository.list_likes(
            limit=max(self._likes_cache_max_items, self._likes_background_target_items)
        )
        recent_videos: list[YouTubeVideo] = []
        for row in cached_rows:
            liked_at = _parse_datetime_utc(row.liked_at)
            if liked_at is None:
                continue
            if cutoff is not None and liked_at < cutoff:
                continue
            recent_videos.append(_cached_like_to_video(row))
        transcript_texts = self._cache_repository.get_cached_transcript_texts(
            video_ids=[video.video_id for video in recent_videos]
        )
        matches = _search_recent_content_matches(
            query=query,
            videos=recent_videos,
            transcript_texts=transcript_texts,
        )
        return matches, recent_videos, transcript_texts

    def list_recent_cached_only_with_metadata(
        self,
        limit: int,
        query: str | None = None,
        *,
        cursor: int = 0,
        probe_recent_on_miss: bool = False,
        recent_probe_pages: int = 1,
    ) -> YouTubeListRecentResult:
        normalized_limit = max(1, min(100, limit))
        normalized_cursor = max(0, cursor)
        if self._cache_repository is None:
            raise YouTubeServiceError("YouTube cache repository is required for cached likes flow")

        estimated_api_units = 0
        probe_pages_used = 0
        recent_probe_applied = False

        cached_rows = self._cache_repository.list_likes(limit=self._likes_cache_max_items)
        active_videos = [_cached_like_to_video(row) for row in cached_rows]
        filtered = active_videos if query is None else _filter_videos_by_query(active_videos, query)
        cache_miss = query is not None and not filtered

        if cache_miss and probe_recent_on_miss:
            probe_units, probe_pages_used = self._probe_recent_likes_cache(
                recent_probe_pages=recent_probe_pages,
                enrich_metadata=True,
            )
            estimated_api_units += probe_units
            recent_probe_applied = probe_pages_used > 0

            refreshed_rows = self._cache_repository.list_likes(limit=self._likes_cache_max_items)
            active_videos = [_cached_like_to_video(row) for row in refreshed_rows]
            filtered = (
                active_videos if query is None else _filter_videos_by_query(active_videos, query)
            )
            cache_miss = query is not None and not filtered

        total_matches = len(filtered)
        page_start = min(normalized_cursor, total_matches)
        page_end = min(total_matches, page_start + normalized_limit)
        videos = filtered[page_start:page_end]
        has_more = page_end < total_matches
        next_cursor = page_end if has_more else None

        LOGGER.info(
            (
                "youtube likes cache_only query=%s limit=%s cursor=%s rows=%s total_matches=%s "
                "has_more=%s next_cursor=%s cache_populated=%s cache_miss=%s "
                "recent_probe_applied=%s recent_probe_pages_used=%s"
            ),
            query,
            normalized_limit,
            page_start,
            len(videos),
            total_matches,
            has_more,
            next_cursor,
            bool(active_videos),
            cache_miss,
            recent_probe_applied,
            probe_pages_used,
        )
        return YouTubeListRecentResult(
            videos=videos,
            estimated_api_units=estimated_api_units,
            cache_hit=bool(active_videos),
            refreshed=recent_probe_applied,
            cache_miss=cache_miss,
            recent_probe_applied=recent_probe_applied,
            recent_probe_pages_used=probe_pages_used,
            cursor=page_start,
            next_cursor=next_cursor,
            has_more=has_more,
            total_matches=total_matches,
            applied_limit=normalized_limit,
        )

    def list_recent_with_metadata(
        self, limit: int, query: str | None = None
    ) -> YouTubeListRecentResult:
        normalized_limit = max(1, min(100, limit))
        if self._cache_repository is None:
            oauth_fetch = self._list_recent_oauth(
                limit=normalized_limit,
                enrich_metadata=query is not None,
            )
            videos = oauth_fetch.videos
            if query is not None:
                videos = _filter_videos_by_query(videos, query)[:normalized_limit]

            return YouTubeListRecentResult(
                videos=videos,
                estimated_api_units=oauth_fetch.estimated_api_units,
                cache_hit=False,
                refreshed=True,
            )

        return self._list_recent_oauth_with_cache(limit=normalized_limit, query=query)

    def get_transcript(self, video_id: str) -> YouTubeTranscript:
        return self.get_transcript_with_metadata(video_id).transcript

    def get_transcript_with_metadata(self, video_id: str) -> YouTubeTranscriptResult:
        if self._cache_repository is not None:
            cached_transcript = self._cache_repository.get_fresh_transcript(
                video_id=video_id,
                ttl_seconds=self._transcript_cache_ttl_seconds,
            )
            if cached_transcript is not None:
                LOGGER.info("youtube transcript cache_hit video_id=%s", video_id)
                return YouTubeTranscriptResult(
                    transcript=YouTubeTranscript(
                        video_id=cached_transcript.video_id,
                        title=cached_transcript.title,
                        transcript=cached_transcript.transcript,
                        source=cached_transcript.source,
                        segments=_clone_segments(cached_transcript.segments),
                    ),
                    estimated_api_units=0,
                    cache_hit=True,
                )

        try:
            transcript, provider_request_id = self._fetch_transcript_with_supadata(video_id)
        except YouTubeServiceError:
            raise
        except Exception as exc:
            raise YouTubeServiceError(f"Failed to fetch transcript from provider: {exc}") from exc
        if transcript is not None:
            if self._cache_repository is not None:
                segments_payload: list[dict[str, object]] = []
                for segment in transcript.segments:
                    payload_segment: dict[str, object] = {}
                    text = segment.get("text")
                    if isinstance(text, str):
                        payload_segment["text"] = text
                    start = segment.get("start")
                    if isinstance(start, (int, float)):
                        payload_segment["start"] = float(start)
                    duration = segment.get("duration")
                    if isinstance(duration, (int, float)):
                        payload_segment["duration"] = float(duration)
                    if payload_segment:
                        segments_payload.append(payload_segment)

                self._cache_repository.upsert_transcript(
                    video_id=transcript.video_id,
                    title=transcript.title,
                    transcript=transcript.transcript,
                    source=transcript.source,
                    initial_request_source=self._infer_transcript_initial_request_source(video_id),
                    segments=segments_payload,
                )
                LOGGER.info("youtube transcript cache_store video_id=%s", video_id)

            return YouTubeTranscriptResult(
                transcript=transcript,
                estimated_api_units=1,
                cache_hit=False,
                provider_request_id=provider_request_id,
            )

        raise SupadataTranscriptError(
            _with_provider_request_id(
                "Transcript unavailable from the configured transcript provider.",
                provider_request_id,
            )
        )

    def _infer_transcript_initial_request_source(self, video_id: str) -> str | None:
        if self._cache_repository is None:
            return None
        likes_match = self._cache_repository.get_likes_by_video_ids(video_ids=[video_id])
        if video_id in likes_match:
            return "likes"
        watch_later_match = self._cache_repository.get_watch_later_by_video_ids(
            video_ids=[video_id]
        )
        watch_later_row = watch_later_match.get(video_id)
        if watch_later_row is not None and watch_later_row.status == WATCH_LATER_STATUS_ACTIVE:
            return "watch_later"
        return None

    def _list_recent_oauth_with_cache(
        self,
        *,
        limit: int,
        query: str | None,
    ) -> YouTubeListRecentResult:
        if self._cache_repository is None:
            raise YouTubeServiceError("YouTube cache repository is required for cached likes flow")

        cached_rows = self._cache_repository.list_likes(limit=self._likes_cache_max_items)
        cached_videos = [_cached_like_to_video(row) for row in cached_rows]
        last_sync_at = self._cache_repository.get_likes_last_sync_at()

        now = datetime.now(UTC)
        cache_age = (now - last_sync_at) if last_sync_at is not None else None
        cache_stale = cache_age is None or cache_age > timedelta(
            seconds=self._likes_cache_ttl_seconds
        )
        within_recent_guard = cache_age is not None and cache_age <= timedelta(
            seconds=self._likes_recent_guard_seconds
        )
        query_requests_recent = query is not None and _query_has_recency_signal(query)
        needs_initial_refresh = (
            not cached_videos
            or cache_stale
            or len(cached_videos) < limit
            or (query_requests_recent and within_recent_guard)
        )

        active_videos = cached_videos
        estimated_api_units = 0
        refreshed = False
        cache_hit = bool(cached_videos) and not needs_initial_refresh

        if needs_initial_refresh:
            try:
                oauth_fetch = self._refresh_likes_cache(
                    limit=max(limit, self._likes_cache_max_items),
                    enrich_metadata=query is not None,
                )
                active_videos = oauth_fetch.videos
                estimated_api_units += oauth_fetch.estimated_api_units
                refreshed = True
                cache_hit = False
            except YouTubeServiceError:
                if not cached_videos:
                    raise
                LOGGER.warning(
                    "youtube likes cache_refresh_failed using_stale_cache reason=initial_refresh",
                    exc_info=True,
                )

        filtered = active_videos if query is None else _filter_videos_by_query(active_videos, query)

        query_miss = query is not None and not filtered
        sparse_metadata = _contains_sparse_metadata(active_videos)
        if (
            query_miss
            and query is not None
            and not refreshed
            and (
                sparse_metadata
                or query_requests_recent
                or cache_age is None
                or cache_age > timedelta(seconds=self._likes_recent_guard_seconds)
            )
        ):
            try:
                oauth_fetch = self._refresh_likes_cache(
                    limit=max(limit, self._likes_cache_max_items),
                    enrich_metadata=True,
                )
                active_videos = oauth_fetch.videos
                estimated_api_units += oauth_fetch.estimated_api_units
                refreshed = True
                cache_hit = False
                filtered = _filter_videos_by_query(active_videos, query)
            except YouTubeServiceError:
                LOGGER.warning(
                    "youtube likes cache_refresh_failed using_cached_query_miss sparse_metadata=%s",
                    sparse_metadata,
                    exc_info=True,
                )

        videos = filtered[:limit]
        if cache_hit:
            LOGGER.info(
                "youtube likes cache_hit query=%s limit=%s rows=%s", query, limit, len(videos)
            )
        elif refreshed:
            LOGGER.info(
                "youtube likes cache_refreshed query=%s limit=%s rows=%s units=%s",
                query,
                limit,
                len(videos),
                estimated_api_units,
            )

        return YouTubeListRecentResult(
            videos=videos,
            estimated_api_units=estimated_api_units,
            cache_hit=cache_hit,
            refreshed=refreshed,
        )

    def _refresh_likes_cache(self, *, limit: int, enrich_metadata: bool) -> _OAuthLikedFetch:
        oauth_fetch = self._list_recent_oauth(
            limit=max(1, limit),
            enrich_metadata=enrich_metadata,
        )
        scoped_videos, _reached_cutoff = self._filter_likes_videos_by_cutoff(oauth_fetch.videos)
        if self._cache_repository is not None:
            cached_rows = [_video_to_cached_like(video) for video in scoped_videos]
            self._cache_repository.upsert_likes(
                videos=cached_rows,
                max_items=None,
            )
            self._apply_likes_cache_scope(source="likes_refresh")
        return _OAuthLikedFetch(
            videos=scoped_videos,
            estimated_api_units=oauth_fetch.estimated_api_units,
        )

    def _list_recent_oauth(self, limit: int, *, enrich_metadata: bool) -> _OAuthLikedFetch:
        client = self._build_oauth_client()

        try:
            oauth_fetch = _list_from_liked_videos(client, limit, enrich_metadata=False)
        except Exception as exc:
            raise YouTubeServiceError(
                f"Failed to fetch liked videos for OAuth user: {exc}"
            ) from exc

        videos, metadata_calls = self._enrich_videos_from_cache_then_api(
            client=client,
            videos=oauth_fetch.videos,
            enrich_metadata=enrich_metadata,
        )
        if not videos:
            raise YouTubeServiceError("No liked videos available for this OAuth account.")

        return _OAuthLikedFetch(
            videos=videos[:limit],
            estimated_api_units=oauth_fetch.estimated_api_units + metadata_calls,
        )

    def _fetch_transcript_with_supadata(
        self, video_id: str
    ) -> tuple[YouTubeTranscript | None, str | None]:
        if self._supadata_api_key is None:
            raise SupadataTranscriptError(
                "Supadata API key is missing. Set ACTIVE_WORKBENCH_SUPADATA_API_KEY."
            )

        snippet = self._fetch_video_snippet(video_id)
        title = snippet.title
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        modes_to_try: list[str] = [self._supadata_transcript_mode]
        if self._supadata_transcript_mode != "generate":
            modes_to_try.append("generate")

        last_request_id: str | None = None
        previous_unavailable_message: str | None = None

        for mode_index, mode in enumerate(modes_to_try):
            poll_interval_override = (
                SUPADATA_GENERATE_FALLBACK_POLL_INTERVAL_SECONDS if mode == "generate" else None
            )
            status_code, payload, request_id = self._request_supadata_transcript(
                video_url=video_url,
                mode=mode,
                poll_interval_seconds=poll_interval_override,
            )
            if request_id is not None:
                last_request_id = request_id

            if status_code >= 400:
                message = _build_supadata_http_error_message(
                    payload=payload,
                    status_code=status_code,
                    endpoint="/v1/transcript",
                    mode=mode,
                )
                if (
                    status_code == 403
                    and mode == "generate"
                    and previous_unavailable_message is not None
                    and _is_supadata_forbidden(payload)
                ):
                    if _is_supadata_age_restricted_forbidden(payload):
                        LOGGER.warning(
                            (
                                "youtube transcript supadata age_restricted_fallback_youtube_api "
                                "video_id=%s provider_request_id=%s previous_mode=%s mode=generate"
                            ),
                            video_id,
                            request_id,
                            self._supadata_transcript_mode,
                        )
                        youtube_transcript = self._fetch_transcript_with_youtube_api_fallback(
                            video_id=video_id,
                            title=title,
                            supadata_request_id=request_id,
                        )
                        return youtube_transcript, request_id
                    raise TranscriptExcludedVideoError(
                        _with_provider_request_id(
                            (
                                "members_only_inferred_from_supadata "
                                f"previous_attempt={previous_unavailable_message}; {message}"
                            ),
                            request_id,
                        )
                    )
                raise SupadataTranscriptError(_with_provider_request_id(message, request_id))

            segments = _extract_supadata_segments(payload)
            transcript_text = _extract_supadata_transcript_text(payload, segments=segments)
            if transcript_text:
                return (
                    YouTubeTranscript(
                        video_id=video_id,
                        title=title,
                        transcript=transcript_text,
                        source="supadata_captions",
                        segments=segments,
                    ),
                    request_id,
                )

            unavailable_message = _build_supadata_transcript_unavailable_message(
                payload=payload,
                status_code=status_code,
            )
            is_unavailable = _is_supadata_transcript_unavailable(payload)
            has_generate_fallback = (
                mode_index < len(modes_to_try) - 1 and modes_to_try[mode_index + 1] == "generate"
            )
            if is_unavailable and has_generate_fallback:
                previous_unavailable_message = unavailable_message
                LOGGER.warning(
                    (
                        "youtube transcript supadata fallback_generate "
                        "video_id=%s provider_request_id=%s previous_mode=%s next_mode=generate "
                        "poll_interval_seconds=%s reason=%s"
                    ),
                    video_id,
                    request_id,
                    mode,
                    int(SUPADATA_GENERATE_FALLBACK_POLL_INTERVAL_SECONDS),
                    unavailable_message,
                )
                continue

            if previous_unavailable_message is not None and mode == "generate" and is_unavailable:
                unavailable_message = (
                    f"{unavailable_message}; previous_attempt={previous_unavailable_message}"
                )
            raise SupadataTranscriptError(
                _with_provider_request_id(unavailable_message, request_id)
            )

        raise SupadataTranscriptError(
            _with_provider_request_id(
                "Supadata transcript unavailable after generate fallback.", last_request_id
            )
        )

    def _fetch_transcript_with_youtube_api_fallback(
        self,
        *,
        video_id: str,
        title: str,
        supadata_request_id: str | None,
    ) -> YouTubeTranscript:
        now = datetime.now(UTC)
        last_query_at = self._get_youtube_transcript_api_fallback_last_query_at()
        if last_query_at is not None:
            elapsed_seconds = (now - last_query_at).total_seconds()
            remaining_seconds = max(
                0,
                int(YOUTUBE_TRANSCRIPT_API_FALLBACK_MIN_INTERVAL_SECONDS - elapsed_seconds),
            )
            if remaining_seconds > 0:
                raise SupadataTranscriptError(
                    _with_provider_request_id(
                        (
                            "YouTube transcript API fallback is locally throttled; "
                            f"retry after {remaining_seconds} seconds."
                        ),
                        supadata_request_id,
                    )
                )

        self._mark_youtube_transcript_api_fallback_query(now)
        try:
            transcript_text, segments = _fetch_transcript_with_youtube_oauth_captions_api(
                video_id=video_id,
                data_dir=self._data_dir,
                token_path=self._oauth_token_path,
                secrets_path=self._oauth_client_secret_path,
            )
        except Exception as exc:
            if _is_youtube_data_api_rate_limit_error(exc):
                retry_after_seconds = (
                    _extract_retry_after_seconds_from_error(exc)
                    or YOUTUBE_TRANSCRIPT_API_FALLBACK_MIN_INTERVAL_SECONDS
                )
                raise SupadataTranscriptError(
                    _with_provider_request_id(
                        (
                            "YouTube transcript API fallback was rate-limited; "
                            f"retry after {retry_after_seconds} seconds. {exc}"
                        ),
                        supadata_request_id,
                    )
                ) from exc
            raise SupadataTranscriptError(
                _with_provider_request_id(
                    f"YouTube transcript API fallback failed: {exc}",
                    supadata_request_id,
                )
            ) from exc

        return YouTubeTranscript(
            video_id=video_id,
            title=title,
            transcript=transcript_text,
            source="youtube_api_captions",
            segments=segments,
        )

    def _get_youtube_transcript_api_fallback_last_query_at(self) -> datetime | None:
        if self._cache_repository is not None:
            raw = self._cache_repository.get_cache_state_value(
                TRANSCRIPTS_YOUTUBE_API_FALLBACK_LAST_QUERY_AT_KEY
            )
            return _parse_datetime_utc(raw)
        return self._youtube_transcript_api_fallback_last_query_at_in_memory

    def _mark_youtube_transcript_api_fallback_query(self, when: datetime) -> None:
        normalized = when.astimezone(UTC)
        self._youtube_transcript_api_fallback_last_query_at_in_memory = normalized
        if self._cache_repository is not None:
            self._cache_repository.set_cache_state_value(
                key=TRANSCRIPTS_YOUTUBE_API_FALLBACK_LAST_QUERY_AT_KEY,
                value=normalized.isoformat().replace("+00:00", "Z"),
            )

    def _request_supadata_transcript(
        self,
        *,
        video_url: str,
        mode: str,
        poll_interval_seconds: float | None = None,
    ) -> tuple[int, dict[str, Any], str | None]:
        status_code, payload = _fetch_supadata_json(
            url=f"{self._supadata_base_url}/transcript",
            api_key=self._supadata_api_key or "",
            timeout_seconds=self._supadata_http_timeout_seconds,
            params={
                "url": video_url,
                "text": "false",
                "mode": mode,
            },
        )
        request_id = _extract_supadata_request_id(payload)
        if status_code != 202:
            return status_code, payload, request_id

        job_id = _extract_supadata_job_id(payload)
        if job_id is None:
            raise SupadataTranscriptError(
                _with_provider_request_id(
                    "Supadata transcript job was accepted but no job ID was returned.",
                    request_id,
                )
            )
        LOGGER.info(
            (
                "youtube transcript supadata async_job "
                "mode=%s job_id=%s provider_request_id=%s poll_interval_seconds=%s"
            ),
            mode,
            job_id,
            request_id,
            int(
                poll_interval_seconds
                if poll_interval_seconds is not None
                else self._supadata_poll_interval_seconds
            ),
        )
        poll_status_code, payload, poll_request_id = self._poll_supadata_transcript_job(
            job_id,
            mode=mode,
            poll_interval_seconds=poll_interval_seconds,
        )
        if poll_request_id is not None:
            request_id = poll_request_id
        return poll_status_code, payload, request_id

    def _poll_supadata_transcript_job(
        self,
        job_id: str,
        *,
        mode: str | None = None,
        poll_interval_seconds: float | None = None,
    ) -> tuple[int, dict[str, Any], str | None]:
        request_id: str | None = None
        effective_poll_interval_seconds = (
            self._supadata_poll_interval_seconds
            if poll_interval_seconds is None
            else max(0.2, poll_interval_seconds)
        )
        for attempt in range(self._supadata_poll_max_attempts):
            status_code, payload = _fetch_supadata_json(
                url=f"{self._supadata_base_url}/transcript/{job_id}",
                api_key=self._supadata_api_key or "",
                timeout_seconds=self._supadata_http_timeout_seconds,
                params=None,
            )
            current_request_id = _extract_supadata_request_id(payload)
            if current_request_id is not None:
                request_id = current_request_id

            if status_code == 206:
                return status_code, payload, request_id
            if status_code >= 400:
                message = _build_supadata_http_error_message(
                    payload=payload,
                    status_code=status_code,
                    endpoint=f"/v1/transcript/{job_id}",
                    mode=mode,
                    job_id=job_id,
                )
                raise SupadataTranscriptError(_with_provider_request_id(message, request_id))

            job_status = _extract_supadata_job_status(payload)
            if job_status is not None and job_status in SUPADATA_PENDING_JOB_STATUSES:
                if attempt < self._supadata_poll_max_attempts - 1:
                    time.sleep(effective_poll_interval_seconds)
                    continue
                raise SupadataTranscriptError(
                    _with_provider_request_id(
                        "Supadata transcript job timed out before completion.",
                        request_id,
                    )
                )

            return status_code, payload, request_id

        raise SupadataTranscriptError(
            _with_provider_request_id(
                "Supadata transcript job timed out before completion.",
                request_id,
            )
        )


def _search_recent_content_matches(
    *,
    query: str,
    videos: list[YouTubeVideo],
    transcript_texts: dict[str, str],
) -> list[YouTubeRecentContentMatch]:
    normalized_query = query.lower().strip()
    query_tokens = _query_tokens(normalized_query)
    if not query_tokens and normalized_query:
        query_tokens = [normalized_query]

    matches: list[YouTubeRecentContentMatch] = []
    for video in videos:
        transcript_text = transcript_texts.get(video.video_id)
        fields: list[tuple[str, str, int]] = [
            ("title", video.title, 8),
            ("description", video.description or "", 5),
            ("transcript", transcript_text or "", 3),
        ]

        matched_fields: list[str] = []
        score = 0
        for field_name, text, weight in fields:
            if not text:
                continue
            field_score = _field_match_score(
                text=text,
                normalized_query=normalized_query,
                query_tokens=query_tokens,
                weight=weight,
            )
            if field_score <= 0:
                continue
            matched_fields.append(field_name)
            score += field_score

        if score <= 0:
            continue

        snippet: str | None = None
        if "transcript" in matched_fields and transcript_text:
            snippet = _extract_match_snippet(
                text=transcript_text,
                normalized_query=normalized_query,
                query_tokens=query_tokens,
            )
        elif "description" in matched_fields and video.description:
            snippet = _extract_match_snippet(
                text=video.description,
                normalized_query=normalized_query,
                query_tokens=query_tokens,
            )

        matches.append(
            YouTubeRecentContentMatch(
                video=video,
                score=score,
                matched_in=tuple(matched_fields),
                snippet=snippet,
            )
        )

    matches.sort(
        key=lambda match: (match.score, _video_liked_datetime(match.video)),
        reverse=True,
    )
    return matches


def _field_match_score(
    *,
    text: str,
    normalized_query: str,
    query_tokens: list[str],
    weight: int,
) -> int:
    normalized_text = text.lower()
    score = 0

    if normalized_query and normalized_query in normalized_text:
        score += 2 * weight

    for token in query_tokens:
        if token and token in normalized_text:
            score += weight

    return score


def _extract_match_snippet(
    *,
    text: str,
    normalized_query: str,
    query_tokens: list[str],
) -> str | None:
    compact = " ".join(text.split())
    if not compact:
        return None

    normalized_compact = compact.lower()
    index = -1
    if normalized_query:
        index = normalized_compact.find(normalized_query)
    if index < 0:
        for token in query_tokens:
            index = normalized_compact.find(token)
            if index >= 0:
                break

    if index < 0:
        return compact[:160]

    start = max(0, index - 70)
    end = min(len(compact), index + 90)
    snippet = compact[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(compact):
        snippet = snippet + "..."
    return snippet


def _parse_datetime_utc(raw_value: str | None) -> datetime | None:
    if raw_value is None:
        return None

    normalized = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _video_liked_datetime(video: YouTubeVideo) -> datetime:
    parsed = _parse_datetime_utc(video.liked_at or video.published_at)
    if parsed is not None:
        return parsed
    return datetime.fromtimestamp(0, tz=UTC)


def _filter_videos_by_query(videos: list[YouTubeVideo], query: str) -> list[YouTubeVideo]:
    normalized_query = query.lower().strip()
    if not normalized_query:
        return videos

    direct_matches = [video for video in videos if normalized_query in _video_search_text(video)]
    if direct_matches:
        return direct_matches

    query_tokens = _query_tokens(normalized_query)
    if not query_tokens:
        return []

    scored: list[tuple[int, int, YouTubeVideo]] = []
    for index, video in enumerate(videos):
        score = _score_video_against_query(video, query_tokens)
        if score > 0:
            scored.append((score, -index, video))

    scored.sort(reverse=True)
    return [video for _, _, video in scored]


def _query_tokens(query: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", query)
    return [token for token in tokens if len(token) >= 3 and token not in QUERY_STOPWORDS]


def _score_video_against_query(video: YouTubeVideo, query_tokens: list[str]) -> int:
    search_text = _video_search_text(video)
    search_tokens = set(re.findall(r"[a-z0-9]+", search_text))

    score = 0
    for token in query_tokens:
        if token in search_tokens:
            score += 3
        elif token in search_text:
            score += 1
    return score


def _video_search_text(video: YouTubeVideo) -> str:
    parts = [
        video.title,
        video.description or "",
        video.channel_title or "",
        " ".join(video.tags),
    ]
    return " ".join(parts).lower()


def _query_has_recency_signal(query: str) -> bool:
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    return any(token in tokens for token in {"latest", "recent", "recently", "new", "just", "last"})


def _contains_sparse_metadata(videos: list[YouTubeVideo]) -> bool:
    return any(_video_needs_metadata_refresh(video) for video in videos)


def _cached_like_to_video(cached_video: CachedLikeVideo) -> YouTubeVideo:
    return YouTubeVideo(
        video_id=cached_video.video_id,
        title=cached_video.title,
        published_at=cached_video.liked_at,
        liked_at=cached_video.liked_at,
        video_published_at=cached_video.video_published_at,
        description=cached_video.description,
        channel_id=cached_video.channel_id,
        channel_title=cached_video.channel_title,
        duration_seconds=cached_video.duration_seconds,
        category_id=cached_video.category_id,
        default_language=cached_video.default_language,
        default_audio_language=cached_video.default_audio_language,
        caption_available=cached_video.caption_available,
        privacy_status=cached_video.privacy_status,
        licensed_content=cached_video.licensed_content,
        made_for_kids=cached_video.made_for_kids,
        live_broadcast_content=cached_video.live_broadcast_content,
        definition=cached_video.definition,
        dimension=cached_video.dimension,
        thumbnails=dict(cached_video.thumbnails),
        topic_categories=cached_video.topic_categories,
        statistics_view_count=cached_video.statistics_view_count,
        statistics_like_count=cached_video.statistics_like_count,
        statistics_comment_count=cached_video.statistics_comment_count,
        statistics_fetched_at=cached_video.statistics_fetched_at,
        tags=cached_video.tags,
    )


def _video_to_cached_like(video: YouTubeVideo) -> CachedLikeVideo:
    return CachedLikeVideo(
        video_id=video.video_id,
        title=video.title,
        liked_at=video.liked_at or video.published_at,
        video_published_at=video.video_published_at,
        description=video.description,
        channel_id=video.channel_id,
        channel_title=video.channel_title,
        duration_seconds=video.duration_seconds,
        category_id=video.category_id,
        default_language=video.default_language,
        default_audio_language=video.default_audio_language,
        caption_available=video.caption_available,
        privacy_status=video.privacy_status,
        licensed_content=video.licensed_content,
        made_for_kids=video.made_for_kids,
        live_broadcast_content=video.live_broadcast_content,
        definition=video.definition,
        dimension=video.dimension,
        thumbnails=dict(video.thumbnails or {}),
        topic_categories=video.topic_categories,
        statistics_view_count=video.statistics_view_count,
        statistics_like_count=video.statistics_like_count,
        statistics_comment_count=video.statistics_comment_count,
        statistics_fetched_at=video.statistics_fetched_at,
        tags=video.tags,
    )


def _cached_watch_later_to_video(cached_video: CachedWatchLaterVideo) -> YouTubeVideo:
    published_at = cached_video.watch_later_added_at or cached_video.last_seen_at
    return YouTubeVideo(
        video_id=cached_video.video_id,
        title=cached_video.title,
        published_at=published_at,
        liked_at=None,
        video_published_at=cached_video.video_published_at,
        description=cached_video.description,
        channel_id=cached_video.channel_id,
        channel_title=cached_video.channel_title,
        duration_seconds=cached_video.duration_seconds,
        category_id=cached_video.category_id,
        default_language=cached_video.default_language,
        default_audio_language=cached_video.default_audio_language,
        caption_available=cached_video.caption_available,
        privacy_status=cached_video.privacy_status,
        licensed_content=cached_video.licensed_content,
        made_for_kids=cached_video.made_for_kids,
        live_broadcast_content=cached_video.live_broadcast_content,
        definition=cached_video.definition,
        dimension=cached_video.dimension,
        thumbnails=dict(cached_video.thumbnails),
        topic_categories=cached_video.topic_categories,
        statistics_view_count=cached_video.statistics_view_count,
        statistics_like_count=cached_video.statistics_like_count,
        statistics_comment_count=cached_video.statistics_comment_count,
        statistics_fetched_at=cached_video.statistics_fetched_at,
        tags=cached_video.tags,
    )


def _video_to_cached_watch_later(
    *,
    video: YouTubeVideo,
    existing: CachedWatchLaterVideo,
) -> CachedWatchLaterVideo:
    return CachedWatchLaterVideo(
        video_id=existing.video_id,
        title=video.title or existing.title,
        watch_later_added_at=existing.watch_later_added_at,
        first_seen_at=existing.first_seen_at,
        last_seen_at=existing.last_seen_at,
        status=existing.status,
        removed_at=existing.removed_at,
        snapshot_position=existing.snapshot_position,
        video_published_at=video.video_published_at,
        description=video.description,
        channel_id=video.channel_id,
        channel_title=video.channel_title,
        duration_seconds=video.duration_seconds,
        category_id=video.category_id,
        default_language=video.default_language,
        default_audio_language=video.default_audio_language,
        caption_available=video.caption_available,
        privacy_status=video.privacy_status,
        licensed_content=video.licensed_content,
        made_for_kids=video.made_for_kids,
        live_broadcast_content=video.live_broadcast_content,
        definition=video.definition,
        dimension=video.dimension,
        thumbnails=dict(video.thumbnails or {}),
        topic_categories=video.topic_categories,
        statistics_view_count=video.statistics_view_count,
        statistics_like_count=video.statistics_like_count,
        statistics_comment_count=video.statistics_comment_count,
        statistics_fetched_at=video.statistics_fetched_at,
        tags=video.tags,
    )


def _metadata_from_cached_like(video: CachedLikeVideo) -> _VideoMetadata:
    return _VideoMetadata(
        description=video.description,
        channel_id=video.channel_id,
        channel_title=video.channel_title,
        duration_seconds=video.duration_seconds,
        category_id=video.category_id,
        default_language=video.default_language,
        default_audio_language=video.default_audio_language,
        caption_available=video.caption_available,
        privacy_status=video.privacy_status,
        licensed_content=video.licensed_content,
        made_for_kids=video.made_for_kids,
        live_broadcast_content=video.live_broadcast_content,
        definition=video.definition,
        dimension=video.dimension,
        thumbnails=dict(video.thumbnails),
        topic_categories=video.topic_categories,
        statistics_view_count=video.statistics_view_count,
        statistics_like_count=video.statistics_like_count,
        statistics_comment_count=video.statistics_comment_count,
        statistics_fetched_at=video.statistics_fetched_at,
        tags=video.tags,
    )


def _metadata_from_cached_watch_later(video: CachedWatchLaterVideo) -> _VideoMetadata:
    return _VideoMetadata(
        description=video.description,
        channel_id=video.channel_id,
        channel_title=video.channel_title,
        duration_seconds=video.duration_seconds,
        category_id=video.category_id,
        default_language=video.default_language,
        default_audio_language=video.default_audio_language,
        caption_available=video.caption_available,
        privacy_status=video.privacy_status,
        licensed_content=video.licensed_content,
        made_for_kids=video.made_for_kids,
        live_broadcast_content=video.live_broadcast_content,
        definition=video.definition,
        dimension=video.dimension,
        thumbnails=dict(video.thumbnails),
        topic_categories=video.topic_categories,
        statistics_view_count=video.statistics_view_count,
        statistics_like_count=video.statistics_like_count,
        statistics_comment_count=video.statistics_comment_count,
        statistics_fetched_at=video.statistics_fetched_at,
        tags=video.tags,
    )


def _video_to_metadata(video: YouTubeVideo) -> _VideoMetadata:
    return _VideoMetadata(
        description=video.description,
        channel_id=video.channel_id,
        channel_title=video.channel_title,
        duration_seconds=video.duration_seconds,
        category_id=video.category_id,
        default_language=video.default_language,
        default_audio_language=video.default_audio_language,
        caption_available=video.caption_available,
        privacy_status=video.privacy_status,
        licensed_content=video.licensed_content,
        made_for_kids=video.made_for_kids,
        live_broadcast_content=video.live_broadcast_content,
        definition=video.definition,
        dimension=video.dimension,
        thumbnails=dict(video.thumbnails or {}),
        topic_categories=video.topic_categories,
        statistics_view_count=video.statistics_view_count,
        statistics_like_count=video.statistics_like_count,
        statistics_comment_count=video.statistics_comment_count,
        statistics_fetched_at=video.statistics_fetched_at,
        tags=video.tags,
    )


def _merge_video_metadata(
    video: YouTubeVideo,
    metadata: _VideoMetadata,
    *,
    overwrite: bool = False,
) -> YouTubeVideo:
    def _merged_str(current: str | None, incoming: str | None) -> str | None:
        if incoming is None:
            return current
        if overwrite or not current:
            return incoming
        return current

    def _merged_int(current: int | None, incoming: int | None) -> int | None:
        if incoming is None:
            return current
        if overwrite or current is None:
            return incoming
        return current

    def _merged_bool(current: bool | None, incoming: bool | None) -> bool | None:
        if incoming is None:
            return current
        if overwrite or current is None:
            return incoming
        return current

    def _merged_tags(current: tuple[str, ...], incoming: tuple[str, ...]) -> tuple[str, ...]:
        if incoming and (overwrite or not current):
            return incoming
        return current

    def _merged_thumbnails(
        current: dict[str, str] | None,
        incoming: dict[str, str] | None,
    ) -> dict[str, str]:
        current_map = dict(current or {})
        if incoming and (overwrite or not current_map):
            return dict(incoming)
        return current_map

    return YouTubeVideo(
        video_id=video.video_id,
        title=video.title,
        published_at=video.published_at,
        liked_at=video.liked_at,
        video_published_at=video.video_published_at,
        description=_merged_str(video.description, metadata.description),
        channel_id=_merged_str(video.channel_id, metadata.channel_id),
        channel_title=_merged_str(video.channel_title, metadata.channel_title),
        duration_seconds=_merged_int(video.duration_seconds, metadata.duration_seconds),
        category_id=_merged_str(video.category_id, metadata.category_id),
        default_language=_merged_str(video.default_language, metadata.default_language),
        default_audio_language=_merged_str(
            video.default_audio_language, metadata.default_audio_language
        ),
        caption_available=_merged_bool(video.caption_available, metadata.caption_available),
        privacy_status=_merged_str(video.privacy_status, metadata.privacy_status),
        licensed_content=_merged_bool(video.licensed_content, metadata.licensed_content),
        made_for_kids=_merged_bool(video.made_for_kids, metadata.made_for_kids),
        live_broadcast_content=_merged_str(
            video.live_broadcast_content, metadata.live_broadcast_content
        ),
        definition=_merged_str(video.definition, metadata.definition),
        dimension=_merged_str(video.dimension, metadata.dimension),
        thumbnails=_merged_thumbnails(video.thumbnails, metadata.thumbnails),
        topic_categories=(
            metadata.topic_categories
            if metadata.topic_categories and (overwrite or not video.topic_categories)
            else video.topic_categories
        ),
        statistics_view_count=_merged_int(
            video.statistics_view_count, metadata.statistics_view_count
        ),
        statistics_like_count=_merged_int(
            video.statistics_like_count, metadata.statistics_like_count
        ),
        statistics_comment_count=_merged_int(
            video.statistics_comment_count,
            metadata.statistics_comment_count,
        ),
        statistics_fetched_at=_merged_str(
            video.statistics_fetched_at, metadata.statistics_fetched_at
        ),
        tags=_merged_tags(video.tags, metadata.tags),
    )


def _video_needs_metadata_refresh(video: YouTubeVideo) -> bool:
    return not video.description and not video.channel_title and not video.tags


def _watch_later_row_needs_metadata(video: CachedWatchLaterVideo) -> bool:
    return not video.description and not video.channel_title and not video.tags


def _clone_segments(segments: list[dict[str, object]]) -> list[dict[str, Any]]:
    cloned: list[dict[str, Any]] = []
    for segment in segments:
        payload: dict[str, Any] = {}
        text = segment.get("text")
        if isinstance(text, str):
            payload["text"] = text

        start = segment.get("start")
        if isinstance(start, (int, float)):
            payload["start"] = float(start)

        duration = segment.get("duration")
        if isinstance(duration, (int, float)):
            payload["duration"] = float(duration)

        if payload:
            cloned.append(payload)
    return cloned


def _fetch_supadata_json(
    *,
    url: str,
    api_key: str,
    timeout_seconds: float,
    params: dict[str, str] | None,
) -> tuple[int, dict[str, Any]]:
    query = urlencode(params or {})
    request_url = f"{url}?{query}" if query else url
    request = Request(
        request_url,
        headers={
            "x-api-key": api_key,
            "accept": "application/json",
            "user-agent": "active-workbench/1.0",
        },
        method="GET",
    )

    status_code = 0
    raw_body = ""
    response_headers: Any = None
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(response.getcode() or 0)
            raw_body = response.read().decode("utf-8", errors="replace")
            response_headers = response.headers
    except HTTPError as exc:
        status_code = int(exc.code)
        raw_body = exc.read().decode("utf-8", errors="replace")
        response_headers = exc.headers
    except (URLError, TimeoutError, OSError) as exc:
        raise SupadataTranscriptError(f"Supadata request failed: {exc}") from exc

    payload = _parse_json_dict(raw_body)
    request_id = _extract_request_id_from_headers(response_headers) or _extract_supadata_request_id(
        payload
    )
    if request_id is None and (status_code >= 400 or status_code == 206):
        LOGGER.debug(
            (
                "supadata response missing request_id status=%s url=%s "
                "response_header_keys=%s response_id_headers=%s payload_top_keys=%s"
            ),
            status_code,
            url,
            _extract_response_header_keys(response_headers),
            _extract_response_id_like_headers(response_headers),
            sorted(payload.keys()),
        )
    if request_id is not None:
        payload = dict(payload)
        payload["_active_workbench_supadata_request_id"] = request_id
    return status_code, payload


def _with_provider_request_id(message: str, request_id: str | None) -> str:
    if request_id is None:
        return message
    return f"{message} (supadata_request_id={request_id})"


def _extract_request_id_from_headers(headers: Any) -> str | None:
    if headers is None or not hasattr(headers, "get"):
        return None

    for key in (
        "x-request-id",
        "X-Request-Id",
        "request-id",
        "Request-Id",
        "x-supadata-request-id",
        "X-Supadata-Request-Id",
        "supadata-request-id",
        "Supadata-Request-Id",
        "x-correlation-id",
        "X-Correlation-Id",
        "correlation-id",
        "Correlation-Id",
        "x-trace-id",
        "X-Trace-Id",
        "trace-id",
        "Trace-Id",
    ):
        raw_value = headers.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()

    if hasattr(headers, "items"):
        try:
            header_items = list(headers.items())
        except Exception:
            header_items = []
        normalized_items: list[tuple[str, str]] = []
        for raw_key, raw_value in header_items:
            if not isinstance(raw_key, str):
                continue
            value = _coerce_nonempty_string(raw_value)
            if value is None:
                continue
            normalized_items.append((raw_key.strip().lower(), value))

        for key, value in normalized_items:
            if ("request" in key or "correlation" in key or "trace" in key) and "id" in key:
                return value
        for key, value in normalized_items:
            if key in {"id", "x-id", "response-id", "x-response-id"} and _looks_like_request_id(
                value
            ):
                return value
    return None


def _parse_json_dict(raw_body: str) -> dict[str, Any]:
    if not raw_body.strip():
        return {}
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        return {}
    return _as_dict(parsed)


def _extract_response_header_keys(headers: Any) -> list[str]:
    if headers is None or not hasattr(headers, "items"):
        return []
    try:
        items = list(headers.items())
    except Exception:
        return []
    keys: list[str] = []
    for raw_key, _raw_value in items:
        if isinstance(raw_key, str):
            keys.append(raw_key.strip().lower())
    return sorted(set(keys))


def _extract_response_id_like_headers(headers: Any) -> dict[str, str]:
    if headers is None or not hasattr(headers, "items"):
        return {}
    try:
        items = list(headers.items())
    except Exception:
        return {}
    result: dict[str, str] = {}
    for raw_key, raw_value in items:
        if not isinstance(raw_key, str):
            continue
        key = raw_key.strip().lower()
        value = _coerce_nonempty_string(raw_value)
        if value is None:
            continue
        if (
            "id" in key and ("request" in key or "trace" in key or "correlation" in key)
        ) or key in {
            "id",
            "x-id",
            "response-id",
            "x-response-id",
        }:
            result[key] = value
    return result


def _extract_supadata_transcript_text(
    payload: dict[str, Any],
    *,
    segments: list[dict[str, Any]],
) -> str:
    candidate_texts = [
        _coerce_nonempty_string(payload.get("content")),
        _coerce_nonempty_string(payload.get("text")),
        _coerce_nonempty_string(payload.get("transcript")),
    ]
    for container_key in ("data", "result"):
        container = _as_dict(payload.get(container_key))
        candidate_texts.extend(
            [
                _coerce_nonempty_string(container.get("content")),
                _coerce_nonempty_string(container.get("text")),
                _coerce_nonempty_string(container.get("transcript")),
            ]
        )

    for candidate in candidate_texts:
        if candidate is not None:
            return candidate

    lines = [segment.get("text", "").strip() for segment in segments]
    return "\n".join(line for line in lines if line)


def _extract_supadata_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for container in (payload, _as_dict(payload.get("data")), _as_dict(payload.get("result"))):
        raw_content = container.get("content")
        segments = _normalize_supadata_segments(raw_content)
        if segments:
            return segments

        raw_segments = container.get("segments")
        segments = _normalize_supadata_segments(raw_segments)
        if segments:
            return segments
    return []


def _normalize_supadata_segments(raw_segments: object) -> list[dict[str, Any]]:
    if not isinstance(raw_segments, list):
        return []

    segments: list[dict[str, Any]] = []
    for raw_segment in cast(list[Any], raw_segments):
        segment = _as_dict(raw_segment)
        text = _coerce_nonempty_string(segment.get("text")) or _coerce_nonempty_string(
            segment.get("content")
        )
        if text is None:
            continue

        start = _coerce_segment_time(segment.get("offset"), milliseconds=False)
        if start is None:
            start = _coerce_segment_time(segment.get("start"), milliseconds=False)
        if start is None:
            start = _coerce_segment_time(segment.get("offsetMs"), milliseconds=True)
        if start is None:
            start = _coerce_segment_time(segment.get("startMs"), milliseconds=True)

        duration = _coerce_segment_time(segment.get("duration"), milliseconds=False)
        if duration is None:
            duration = _coerce_segment_time(segment.get("durationMs"), milliseconds=True)

        normalized: dict[str, Any] = {"text": text}
        if start is not None:
            normalized["start"] = start
        if duration is not None:
            normalized["duration"] = duration
        segments.append(normalized)
    return segments


def _coerce_segment_time(raw_value: object, *, milliseconds: bool) -> float | None:
    numeric: float | None = None
    if isinstance(raw_value, (int, float)):
        numeric = float(raw_value)
    elif isinstance(raw_value, str):
        try:
            numeric = float(raw_value.strip())
        except ValueError:
            numeric = None

    if numeric is None:
        return None
    if milliseconds:
        numeric /= 1000.0
    return max(0.0, numeric)


def _extract_supadata_job_id(payload: dict[str, Any]) -> str | None:
    for container in (payload, _as_dict(payload.get("data")), _as_dict(payload.get("result"))):
        for key in ("jobId", "job_id", "id"):
            value = _coerce_nonempty_string(container.get(key))
            if value is not None:
                return value
    return None


def _extract_supadata_job_status(payload: dict[str, Any]) -> str | None:
    for container in (payload, _as_dict(payload.get("data")), _as_dict(payload.get("result"))):
        raw_status = _coerce_nonempty_string(container.get("status"))
        if raw_status is not None:
            return raw_status.strip().lower()
    return None


def _extract_supadata_error_message(payload: dict[str, Any]) -> str | None:
    for container in (payload, _as_dict(payload.get("data")), _as_dict(payload.get("result"))):
        for key in ("message", "detail", "error"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = _as_dict(value)
                nested_message = nested.get("message")
                if isinstance(nested_message, str) and nested_message.strip():
                    return nested_message.strip()
    return None


def _extract_supadata_request_id(payload: dict[str, Any]) -> str | None:
    containers = (
        payload,
        _as_dict(payload.get("data")),
        _as_dict(payload.get("result")),
        _as_dict(payload.get("meta")),
        _as_dict(payload.get("metadata")),
    )
    for container in containers:
        for key in (
            "_active_workbench_supadata_request_id",
            "request_id",
            "requestId",
            "x_request_id",
            "xRequestId",
        ):
            value = _coerce_nonempty_string(container.get(key))
            if value is not None:
                return value
        for key in ("trace_id", "traceId", "correlation_id", "correlationId"):
            value = _coerce_nonempty_string(container.get(key))
            if value is not None:
                return value
        generic_id = _coerce_nonempty_string(container.get("id"))
        if generic_id is not None and _looks_like_request_id(generic_id):
            return generic_id
    return None


def _looks_like_request_id(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    if re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", normalized
    ):
        return True
    if len(normalized) < 16:
        return False
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", normalized):
        return False
    return any(ch.isalpha() for ch in normalized) and any(ch.isdigit() for ch in normalized)


def _is_supadata_transcript_unavailable(payload: dict[str, Any]) -> bool:
    for container in (payload, _as_dict(payload.get("data")), _as_dict(payload.get("result"))):
        for key in ("error", "message", "detail", "details"):
            value = container.get(key)
            if not isinstance(value, str):
                continue
            normalized = value.strip().lower()
            if not normalized:
                continue
            if "transcript-unavailable" in normalized or "transcript unavailable" in normalized:
                return True
    return False


def _is_supadata_forbidden(payload: dict[str, Any]) -> bool:
    for container in (payload, _as_dict(payload.get("data")), _as_dict(payload.get("result"))):
        for key in ("error", "message", "detail", "details"):
            value = container.get(key)
            if not isinstance(value, str):
                continue
            normalized = value.strip().lower()
            if not normalized:
                continue
            if normalized == "forbidden":
                return True
    return False


def _is_supadata_age_restricted_forbidden(payload: dict[str, Any]) -> bool:
    for container in (payload, _as_dict(payload.get("data")), _as_dict(payload.get("result"))):
        for key in ("error", "message", "detail", "details"):
            value = container.get(key)
            if not isinstance(value, str):
                continue
            normalized = value.strip().lower()
            if not normalized:
                continue
            if "age-restricted" in normalized:
                return True
            if "requires authentication" in normalized or "requires auth" in normalized:
                return True
    return False


def _build_supadata_transcript_unavailable_message(
    *,
    payload: dict[str, Any],
    status_code: int,
) -> str:
    parts: list[str] = ["Supadata transcript unavailable"]
    code = _extract_supadata_error_code(payload)
    message = _extract_supadata_error_message(payload)
    details = _extract_supadata_error_details(payload)

    if code is not None:
        parts.append(f"code={code}")
    if message is not None:
        parts.append(f"message={message}")
    if details is not None:
        parts.append(f"details={details}")
    parts.append(f"http_status={status_code}")
    return "; ".join(parts)


def _build_supadata_http_error_message(
    *,
    payload: dict[str, Any],
    status_code: int,
    endpoint: str,
    mode: str | None = None,
    job_id: str | None = None,
) -> str:
    parts: list[str] = ["Supadata transcript request failed"]
    parts.append(f"http_status={status_code}")
    parts.append(f"endpoint={endpoint}")
    if mode is not None:
        parts.append(f"mode={mode}")
    if job_id is not None:
        parts.append(f"job_id={job_id}")

    code = _extract_supadata_error_code(payload)
    message = _extract_supadata_error_message(payload)
    details = _extract_supadata_error_details(payload)
    if code is not None:
        parts.append(f"code={code}")
    if message is not None:
        parts.append(f"message={message}")
    if details is not None:
        parts.append(f"details={details}")
    return "; ".join(parts)


def _extract_supadata_error_code(payload: dict[str, Any]) -> str | None:
    for container in (payload, _as_dict(payload.get("data")), _as_dict(payload.get("result"))):
        value = _coerce_nonempty_string(container.get("error"))
        if value is not None:
            return value
    return None


def _extract_supadata_error_details(payload: dict[str, Any]) -> str | None:
    for container in (payload, _as_dict(payload.get("data")), _as_dict(payload.get("result"))):
        for key in ("details", "detail"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = _as_dict(value)
                nested_message = nested.get("message")
                if isinstance(nested_message, str) and nested_message.strip():
                    return nested_message.strip()
    return None


def _normalize_supadata_transcript_mode(raw_value: str) -> str:
    normalized = raw_value.strip().lower()
    if normalized in {"native", "auto", "generate"}:
        return normalized
    return "native"


def _is_youtube_members_only_title(title: str) -> bool:
    normalized = title.strip().lower()
    return normalized in {"members-only video", "members only video"}


def _normalize_supadata_base_url(raw_value: str) -> str:
    trimmed = raw_value.strip()
    if not trimmed:
        return "https://api.supadata.ai/v1"
    return trimmed.rstrip("/")


def _normalize_env_text(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    if not normalized:
        return None
    return normalized


def _build_youtube_client(
    data_dir: Path,
    *,
    token_path: Path | None = None,
    secrets_path: Path | None = None,
) -> Any:
    try:
        requests_module = import_module("google.auth.transport.requests")
        credentials_module = import_module("google.oauth2.credentials")
        flow_module = import_module("google_auth_oauthlib.flow")
        discovery_module = import_module("googleapiclient.discovery")
    except ImportError as exc:  # pragma: no cover - dependency controlled at runtime
        raise YouTubeServiceError(
            "OAuth mode requires google-api-python-client and google-auth-oauthlib dependencies"
        ) from exc

    scope = ["https://www.googleapis.com/auth/youtube.readonly"]
    resolved_token_path, resolved_secrets_path = resolve_oauth_paths(
        data_dir,
        token_override=token_path,
        secret_override=secrets_path,
    )

    request_cls: Any = requests_module.Request
    credentials_cls: Any = credentials_module.Credentials
    flow_cls: Any = flow_module.InstalledAppFlow
    build_fn: Any = discovery_module.build

    credentials: Any | None = None
    if resolved_token_path.exists():
        credentials = credentials_cls.from_authorized_user_file(str(resolved_token_path), scope)

    if credentials is None or not credentials.valid:
        if credentials is not None and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(request_cls())
            except Exception as exc:
                LOGGER.warning(
                    "youtube oauth token_refresh_failed token_path=%s",
                    resolved_token_path,
                    exc_info=True,
                )
                if _oauth_refresh_requires_reauth(exc):
                    raise YouTubeServiceError(
                        "YouTube OAuth token has expired or was revoked. "
                        f"Remove {resolved_token_path} and run `just youtube-auth` to re-authorize."
                    ) from exc
                raise YouTubeServiceError(f"Failed to refresh YouTube OAuth token: {exc}") from exc
        else:
            if not resolved_secrets_path.exists():
                raise YouTubeServiceError(
                    f"Missing OAuth client secret file at {resolved_secrets_path}"
                )

            flow = flow_cls.from_client_secrets_file(str(resolved_secrets_path), scope)
            credentials = flow.run_local_server(port=0)

        if credentials is None:
            raise YouTubeServiceError("OAuth flow did not return credentials")

        resolved_token_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_token_path.write_text(str(credentials.to_json()), encoding="utf-8")

    return build_fn("youtube", "v3", credentials=credentials, cache_discovery=False)


def resolve_oauth_paths(
    data_dir: Path,
    *,
    token_override: Path | None = None,
    secret_override: Path | None = None,
) -> tuple[Path, Path]:
    token_path = (
        token_override.expanduser().resolve()
        if token_override
        else (data_dir / "youtube-token.json").resolve()
    )
    secrets_path = (
        secret_override.expanduser().resolve()
        if secret_override
        else (data_dir / "youtube-client-secret.json").resolve()
    )
    return token_path, secrets_path


def _oauth_refresh_requires_reauth(exc: Exception) -> bool:
    normalized = str(exc).lower()
    return "invalid_grant" in normalized or "expired or revoked" in normalized


def _list_from_liked_videos(
    client: Any,
    limit: int,
    *,
    enrich_metadata: bool,
) -> _OAuthLikedFetch:
    likes_playlist_id = _resolve_likes_playlist_id(client)
    clamped_limit = max(1, limit)

    videos: list[YouTubeVideo] = []
    estimated_api_units = 1  # channels.list in _resolve_likes_playlist_id
    next_page_token: str | None = None

    while len(videos) < clamped_limit:
        page_fetch = _list_liked_videos_page(
            client,
            likes_playlist_id=likes_playlist_id,
            page_size=min(50, clamped_limit - len(videos)),
            page_token=next_page_token,
            enrich_metadata=enrich_metadata,
        )
        estimated_api_units += page_fetch.estimated_api_units
        videos.extend(page_fetch.videos)

        if page_fetch.next_page_token is None:
            break
        next_page_token = page_fetch.next_page_token

    return _OAuthLikedFetch(
        videos=videos,
        estimated_api_units=estimated_api_units,
    )


def _list_liked_videos_page(
    client: Any,
    *,
    likes_playlist_id: str,
    page_size: int,
    page_token: str | None,
    enrich_metadata: bool,
) -> _OAuthLikedPageFetch:
    query_kwargs: dict[str, object] = {
        "part": "snippet,contentDetails",
        "playlistId": likes_playlist_id,
        "maxResults": max(1, min(50, page_size)),
    }
    if page_token is not None:
        query_kwargs["pageToken"] = page_token

    response = cast(
        dict[str, Any],
        client.playlistItems().list(**query_kwargs).execute(),
    )

    videos: list[YouTubeVideo] = []
    excluded_members_only_video_ids: list[str] = []
    for item in _as_list(response.get("items")):
        item_dict = _as_dict(item)
        content_details = _as_dict(item_dict.get("contentDetails"))
        snippet = _as_dict(item_dict.get("snippet"))
        resource = _as_dict(snippet.get("resourceId"))
        video_id = resource.get("videoId")
        title = snippet.get("title")
        liked_at = snippet.get("publishedAt")
        video_published_at_value = content_details.get("videoPublishedAt")
        video_published_at = (
            video_published_at_value if isinstance(video_published_at_value, str) else None
        )

        if isinstance(video_id, str) and isinstance(title, str) and isinstance(liked_at, str):
            if _is_youtube_members_only_title(title):
                excluded_members_only_video_ids.append(video_id)
                LOGGER.info(
                    "youtube likes skip video_id=%s reason=members_only title=%s",
                    video_id,
                    title,
                )
                continue
            videos.append(
                YouTubeVideo(
                    video_id=video_id,
                    title=title,
                    published_at=liked_at,
                    liked_at=liked_at,
                    video_published_at=video_published_at,
                )
            )

    metadata_calls = 0
    if enrich_metadata and videos:
        videos, metadata_calls = _enrich_liked_video_metadata(client, videos)

    raw_next = response.get("nextPageToken")
    next_page_token = raw_next if isinstance(raw_next, str) and raw_next.strip() else None
    return _OAuthLikedPageFetch(
        videos=videos,
        next_page_token=next_page_token,
        estimated_api_units=1 + metadata_calls,
        excluded_members_only_video_ids=tuple(dict.fromkeys(excluded_members_only_video_ids)),
    )


def _enrich_liked_video_metadata(
    client: Any,
    videos: list[YouTubeVideo],
) -> tuple[list[YouTubeVideo], int]:
    video_ids = [video.video_id for video in videos]
    metadata_by_id: dict[str, _VideoMetadata] = {}
    metadata_calls = 0
    stats_fetched_at = datetime.now(UTC).isoformat()

    for index in range(0, len(video_ids), 50):
        chunk = video_ids[index : index + 50]
        response = cast(
            dict[str, Any],
            client.videos()
            .list(
                part="snippet,contentDetails,status,statistics,topicDetails",
                id=",".join(chunk),
                maxResults=len(chunk),
            )
            .execute(),
        )
        metadata_calls += 1

        for item in _as_list(response.get("items")):
            item_dict = _as_dict(item)
            raw_video_id = item_dict.get("id")
            if not isinstance(raw_video_id, str):
                continue

            snippet = _as_dict(item_dict.get("snippet"))
            content_details = _as_dict(item_dict.get("contentDetails"))
            status = _as_dict(item_dict.get("status"))
            statistics = _as_dict(item_dict.get("statistics"))
            topic_details = _as_dict(item_dict.get("topicDetails"))

            description_raw = snippet.get("description")
            description = description_raw if isinstance(description_raw, str) else None

            channel_id_raw = snippet.get("channelId")
            channel_id = channel_id_raw if isinstance(channel_id_raw, str) else None

            channel_raw = snippet.get("channelTitle")
            channel_title = channel_raw if isinstance(channel_raw, str) else None

            category_raw = snippet.get("categoryId")
            category_id = category_raw if isinstance(category_raw, str) else None

            default_language_raw = snippet.get("defaultLanguage")
            default_language = (
                default_language_raw if isinstance(default_language_raw, str) else None
            )

            default_audio_language_raw = snippet.get("defaultAudioLanguage")
            default_audio_language = (
                default_audio_language_raw if isinstance(default_audio_language_raw, str) else None
            )

            live_broadcast_raw = snippet.get("liveBroadcastContent")
            live_broadcast_content = (
                live_broadcast_raw if isinstance(live_broadcast_raw, str) else None
            )

            tags_raw = snippet.get("tags")
            tags: tuple[str, ...] = ()
            if isinstance(tags_raw, list):
                values: list[str] = []
                for raw_tag in cast(list[Any], tags_raw):
                    if isinstance(raw_tag, str):
                        values.append(raw_tag)
                tags = tuple(values)

            duration_seconds = _parse_iso8601_duration_seconds(content_details.get("duration"))
            caption_available = _coerce_bool(content_details.get("caption"))
            definition = _coerce_nonempty_string(content_details.get("definition"))
            dimension = _coerce_nonempty_string(content_details.get("dimension"))

            privacy_status = _coerce_nonempty_string(status.get("privacyStatus"))
            licensed_content = _coerce_bool(status.get("licensedContent"))
            made_for_kids = _coerce_bool(status.get("madeForKids"))

            thumbnails = _extract_thumbnail_urls(snippet)
            topic_categories = _extract_string_list(topic_details.get("topicCategories"))

            statistics_view_count = _coerce_int(statistics.get("viewCount"))
            statistics_like_count = _coerce_int(statistics.get("likeCount"))
            statistics_comment_count = _coerce_int(statistics.get("commentCount"))

            metadata_by_id[raw_video_id] = _VideoMetadata(
                description=description,
                channel_id=channel_id,
                channel_title=channel_title,
                duration_seconds=duration_seconds,
                category_id=category_id,
                default_language=default_language,
                default_audio_language=default_audio_language,
                caption_available=caption_available,
                privacy_status=privacy_status,
                licensed_content=licensed_content,
                made_for_kids=made_for_kids,
                live_broadcast_content=live_broadcast_content,
                definition=definition,
                dimension=dimension,
                thumbnails=thumbnails,
                topic_categories=topic_categories,
                statistics_view_count=statistics_view_count,
                statistics_like_count=statistics_like_count,
                statistics_comment_count=statistics_comment_count,
                statistics_fetched_at=stats_fetched_at,
                tags=tags,
            )

    enriched: list[YouTubeVideo] = []
    for video in videos:
        metadata = metadata_by_id.get(video.video_id)
        if metadata is None:
            enriched.append(video)
            continue

        enriched.append(
            YouTubeVideo(
                video_id=video.video_id,
                title=video.title,
                published_at=video.published_at,
                liked_at=video.liked_at,
                video_published_at=video.video_published_at,
                description=metadata.description,
                channel_id=metadata.channel_id,
                channel_title=metadata.channel_title,
                duration_seconds=metadata.duration_seconds,
                category_id=metadata.category_id,
                default_language=metadata.default_language,
                default_audio_language=metadata.default_audio_language,
                caption_available=metadata.caption_available,
                privacy_status=metadata.privacy_status,
                licensed_content=metadata.licensed_content,
                made_for_kids=metadata.made_for_kids,
                live_broadcast_content=metadata.live_broadcast_content,
                definition=metadata.definition,
                dimension=metadata.dimension,
                thumbnails=dict(metadata.thumbnails or {}),
                topic_categories=metadata.topic_categories,
                statistics_view_count=metadata.statistics_view_count,
                statistics_like_count=metadata.statistics_like_count,
                statistics_comment_count=metadata.statistics_comment_count,
                statistics_fetched_at=metadata.statistics_fetched_at,
                tags=metadata.tags,
            )
        )
    return enriched, metadata_calls


def _resolve_likes_playlist_id(client: Any) -> str:
    response = cast(
        dict[str, Any],
        client.channels().list(part="contentDetails", mine=True, maxResults=1).execute(),
    )

    items = _as_list(response.get("items"))
    if not items:
        return "LL"

    first_item = _as_dict(items[0])
    content_details = _as_dict(first_item.get("contentDetails"))
    related = _as_dict(content_details.get("relatedPlaylists"))
    likes_value = related.get("likes")
    if isinstance(likes_value, str) and likes_value.strip():
        return likes_value
    return "LL"


def _parse_iso8601_duration_seconds(raw_value: object) -> int | None:
    if not isinstance(raw_value, str):
        return None
    matched = ISO8601_DURATION_PATTERN.match(raw_value.strip())
    if matched is None:
        return None

    days = int(matched.group("days") or 0)
    hours = int(matched.group("hours") or 0)
    minutes = int(matched.group("minutes") or 0)
    seconds = int(matched.group("seconds") or 0)
    total_seconds = days * 86_400 + hours * 3_600 + minutes * 60 + seconds
    return total_seconds


def _extract_thumbnail_urls(snippet: dict[str, Any]) -> dict[str, str]:
    thumbnails = _as_dict(snippet.get("thumbnails"))
    urls: dict[str, str] = {}
    for quality, payload in thumbnails.items():
        payload_dict = _as_dict(payload)
        url_value = payload_dict.get("url")
        if isinstance(url_value, str) and url_value.strip():
            urls[quality] = url_value
    return urls


def _coerce_thumbnail_map(raw_value: object) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        return {}
    urls: dict[str, str] = {}
    for raw_quality, raw_payload in cast(dict[object, object], raw_value).items():
        if not isinstance(raw_quality, str):
            continue
        if isinstance(raw_payload, str) and raw_payload.strip():
            urls[raw_quality] = raw_payload
            continue
        if isinstance(raw_payload, dict):
            payload_dict = cast(dict[object, object], raw_payload)
            raw_url = payload_dict.get("url")
            if isinstance(raw_url, str) and raw_url.strip():
                urls[raw_quality] = raw_url
    return urls


def _extract_string_list(raw_value: object) -> tuple[str, ...]:
    if not isinstance(raw_value, list):
        return ()
    values: list[str] = []
    for raw_item in cast(list[Any], raw_value):
        if isinstance(raw_item, str) and raw_item.strip():
            values.append(raw_item)
    return tuple(values)


def _coerce_nonempty_string(raw_value: object) -> str | None:
    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value
    return None


def _coerce_bool(raw_value: object) -> bool | None:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(raw_value, int):
        return bool(raw_value)
    return None


def _coerce_int(raw_value: object) -> int | None:
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)
    if isinstance(raw_value, str):
        try:
            return int(raw_value)
        except ValueError:
            return None
    return None


def _percent_progress(current: int, total: int) -> int:
    if total <= 0:
        return 0
    clamped_current = max(0, min(current, total))
    return int((clamped_current / total) * 100)


def _is_transcript_ip_block_error(exc: Exception) -> bool:
    class_name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    if "ipblocked" in class_name or "requestblocked" in class_name:
        return True
    if "ipblocked" in message or "requestblocked" in message:
        return True
    return "blocking requests from your ip" in message


def _is_youtube_data_api_rate_limit_error(exc: Exception) -> bool:
    class_name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    if "rate" in class_name and "limit" in class_name:
        return True

    markers = (
        "quotaexceeded",
        "dailylimitexceeded",
        "ratelimitexceeded",
        "userratelimitexceeded",
        "quota exceeded",
        "rate limit exceeded",
        "too many requests",
        "http error 429",
        "status code 429",
    )
    return any(marker in message for marker in markers)


def _extract_retry_after_seconds_from_error(exc: Exception) -> int | None:
    response = getattr(exc, "resp", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers is not None:
            retry_after_raw = None
            if hasattr(headers, "get"):
                retry_after_raw = headers.get("Retry-After") or headers.get("retry-after")
            if isinstance(retry_after_raw, str):
                parsed = _parse_retry_after_duration_seconds(retry_after_raw)
                if parsed is not None:
                    return parsed

    return _parse_retry_after_duration_seconds(str(exc))


def _parse_retry_after_duration_seconds(raw_value: str) -> int | None:
    normalized = raw_value.lower()
    match = re.search(
        r"retry(?:\s+after)?\s+(\d+)(?:\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h))?",
        normalized,
    )
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2) or "s"
    if unit.startswith("h"):
        return amount * 3600
    if unit.startswith("m"):
        return amount * 60
    return amount


def _summarize_exception_message(exc: Exception, *, max_length: int = 400) -> str:
    raw = str(exc).strip()
    if not raw:
        raw = repr(exc)
    if len(raw) <= max_length:
        return raw
    return f"{raw[: max_length - 3]}..."


def _fetch_video_snippet(
    video_id: str,
    data_dir: Path,
    *,
    token_path: Path | None = None,
    secrets_path: Path | None = None,
) -> _VideoSnippet:
    client = _build_youtube_client(
        data_dir,
        token_path=token_path,
        secrets_path=secrets_path,
    )
    response = cast(
        dict[str, Any],
        client.videos().list(part="snippet", id=video_id, maxResults=1).execute(),
    )

    items = _as_list(response.get("items"))
    if not items:
        return _VideoSnippet(title=video_id, description=None)

    snippet = _as_dict(_as_dict(items[0]).get("snippet"))
    raw_title = snippet.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else video_id

    raw_description = snippet.get("description")
    description = (
        raw_description.strip()
        if isinstance(raw_description, str) and raw_description.strip()
        else None
    )
    return _VideoSnippet(title=title, description=description)


def _fetch_transcript_with_youtube_oauth_captions_api(
    *,
    video_id: str,
    data_dir: Path,
    token_path: Path | None = None,
    secrets_path: Path | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    client = _build_youtube_client(
        data_dir,
        token_path=token_path,
        secrets_path=secrets_path,
    )

    captions_response = cast(
        dict[str, Any],
        client.captions().list(part="snippet", videoId=video_id).execute(),
    )
    caption_id = _select_youtube_caption_track_id(captions_response)
    if caption_id is None:
        raise YouTubeServiceError("No YouTube caption tracks available for this video.")

    raw_download = client.captions().download(id=caption_id, tfmt="srt").execute()
    if isinstance(raw_download, bytes):
        srt_text = raw_download.decode("utf-8", errors="replace")
    elif isinstance(raw_download, str):
        srt_text = raw_download
    else:
        raise YouTubeServiceError("Unexpected YouTube captions download response format.")

    transcript_text, segments = _parse_srt_transcript(srt_text)
    if not transcript_text.strip():
        raise YouTubeServiceError("YouTube captions download was empty.")
    return transcript_text, segments


def _select_youtube_caption_track_id(response: dict[str, Any]) -> str | None:
    best_fallback: str | None = None
    for item in _as_list(response.get("items")):
        item_dict = _as_dict(item)
        caption_id = _coerce_nonempty_string(item_dict.get("id"))
        if caption_id is None:
            continue
        if best_fallback is None:
            best_fallback = caption_id
        snippet = _as_dict(item_dict.get("snippet"))
        track_kind = _coerce_nonempty_string(snippet.get("trackKind"))
        if track_kind is None or track_kind.strip().lower() != "asr":
            return caption_id
    return best_fallback


def _parse_srt_transcript(srt_text: str) -> tuple[str, list[dict[str, Any]]]:
    normalized = srt_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return "", []

    segments: list[dict[str, Any]] = []
    lines_for_fallback: list[str] = []
    blocks = re.split(r"\n{2,}", normalized)
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        timestamp_line_index = 0
        if len(lines) >= 2 and re.fullmatch(r"\d+", lines[0]):
            timestamp_line_index = 1
        if timestamp_line_index >= len(lines):
            continue

        timestamp_line = lines[timestamp_line_index]
        match = re.match(
            r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})",
            timestamp_line,
        )
        if match is None:
            for line in lines:
                if not re.fullmatch(r"\d+", line) and "-->" not in line:
                    lines_for_fallback.append(line)
            continue

        start_seconds = _parse_srt_timestamp_seconds(match.group("start"))
        end_seconds = _parse_srt_timestamp_seconds(match.group("end"))
        text_lines = lines[timestamp_line_index + 1 :]
        text = "\n".join(text_lines).strip()
        if not text:
            continue

        segment: dict[str, Any] = {"text": text}
        if start_seconds is not None:
            segment["start"] = start_seconds
        if start_seconds is not None and end_seconds is not None and end_seconds >= start_seconds:
            segment["duration"] = end_seconds - start_seconds
        segments.append(segment)
        lines_for_fallback.extend(text_lines)

    if segments:
        transcript_text = "\n".join(
            segment["text"] for segment in segments if isinstance(segment.get("text"), str)
        )
        return transcript_text, segments

    transcript_text = "\n".join(line for line in lines_for_fallback if line).strip()
    return transcript_text, []


def _parse_srt_timestamp_seconds(raw_value: str) -> float | None:
    normalized = raw_value.strip().replace(",", ".")
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})", normalized)
    if match is None:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int(match.group(4))
    return float(hours * 3600 + minutes * 60 + seconds) + (millis / 1000.0)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        raw_dict = cast(dict[object, object], value)
        converted: dict[str, Any] = {}
        for key, item in raw_dict.items():
            if isinstance(key, str):
                converted[key] = item
        return converted
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        raw_list = cast(list[Any], value)
        return list(raw_list)
    return []
