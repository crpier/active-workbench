from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from backend.app.repositories.youtube_cache_repository import (
    CachedLikeVideo,
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


@dataclass(frozen=True)
class YouTubeTranscriptResult:
    transcript: YouTubeTranscript
    estimated_api_units: int
    cache_hit: bool


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


class YouTubeServiceError(Exception):
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


class YouTubeTranscriptIpBlockedError(YouTubeServiceError):
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

PREFERRED_TRANSCRIPT_LANGUAGES: tuple[str, ...] = (
    "en",
    "en-US",
    "en-GB",
    "ro",
    "de",
    "fr",
    "es",
    "it",
)

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
TRANSCRIPTS_BACKGROUND_LAST_RUN_AT_KEY = "transcripts_background_last_run_at"
TRANSCRIPTS_BACKGROUND_IP_BLOCK_PAUSED_UNTIL_KEY = "transcripts_background_ip_block_paused_until"
TRANSCRIPTS_BACKGROUND_IP_BLOCK_STREAK_KEY = "transcripts_background_ip_block_streak"
LIKES_RECENT_PROBE_RATE_LIMIT_BASE_SECONDS = 900
LIKES_RECENT_PROBE_RATE_LIMIT_MAX_SECONDS = 86_400
ISO8601_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


FIXTURE_VIDEOS: list[YouTubeVideo] = [
    YouTubeVideo(
        video_id="fixture_cooking_001",
        title="How To Cook Leek And Potato Soup",
        published_at="2026-02-06T18:00:00+00:00",
        liked_at="2026-02-06T18:00:00+00:00",
        video_published_at="2026-02-06T18:00:00+00:00",
        description="Simple leek soup tutorial with potato and stock.",
        channel_title="Fixture Cooking",
        tags=("soup", "leek", "recipe"),
    ),
    YouTubeVideo(
        video_id="fixture_micro_001",
        title="Microservices Done Right - Real Lessons",
        published_at="2026-02-05T19:30:00+00:00",
        liked_at="2026-02-05T19:30:00+00:00",
        video_published_at="2026-02-05T19:30:00+00:00",
        description="Architecture trade-offs and distributed systems pitfalls.",
        channel_title="Fixture Engineering",
        tags=("microservices", "architecture"),
    ),
    YouTubeVideo(
        video_id="fixture_general_001",
        title="Weekly Productivity Systems",
        published_at="2026-02-04T15:00:00+00:00",
        liked_at="2026-02-04T15:00:00+00:00",
        video_published_at="2026-02-04T15:00:00+00:00",
        description="A review of GPT-5.3 pros and cons for coding productivity.",
        channel_title="Fixture AI",
        tags=("gpt-5.3", "llm", "productivity"),
    ),
]

FIXTURE_TRANSCRIPTS: dict[str, YouTubeTranscript] = {
    "fixture_cooking_001": YouTubeTranscript(
        video_id="fixture_cooking_001",
        title="How To Cook Leek And Potato Soup",
        source="fixture",
        transcript="""
Today we're cooking a leek and potato soup.
Ingredients: 2 leeks, 3 potatoes, 2 tbsp olive oil, 1 liter vegetable stock, salt, pepper.
Chop the leeks and potatoes.
Heat oil in a pot and add chopped leeks. Stir for 5 minutes.
Add potatoes and stock, then simmer for 25 minutes.
Blend until smooth, add salt and pepper, and serve warm.
""".strip(),
        segments=[],
    ),
    "fixture_micro_001": YouTubeTranscript(
        video_id="fixture_micro_001",
        title="Microservices Done Right - Real Lessons",
        source="fixture",
        transcript="""
Microservices help teams deploy independently, but they increase operational complexity.
Start with clear service boundaries and avoid sharing databases.
Observability is critical: tracing, metrics, and logs must be designed from day one.
Failure isolation and retries are useful, but uncontrolled retries can create cascading failures.
Use asynchronous messaging when latency tolerance allows it.
""".strip(),
        segments=[],
    ),
}


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
        likes_background_target_items: int = 1_000,
        transcript_cache_ttl_seconds: int = 86_400,
        transcript_background_sync_enabled: bool = True,
        transcript_background_min_interval_seconds: int = 20,
        transcript_background_recent_limit: int = 1_000,
        transcript_background_backoff_base_seconds: int = 300,
        transcript_background_backoff_max_seconds: int = 86_400,
        transcript_background_ip_block_pause_seconds: int = 7_200,
    ) -> None:
        self._mode = mode
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
        self._likes_background_target_items = max(
            self._likes_background_page_size,
            likes_background_target_items,
        )
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

    @property
    def is_oauth_mode(self) -> bool:
        return self._mode == "oauth"

    def run_background_likes_sync(self) -> None:
        if (
            self._mode != "oauth"
            or not self._likes_background_sync_enabled
            or self._cache_repository is None
        ):
            return

        if not self._background_sync_interval_elapsed():
            return

        likes_rows_before = self._cache_repository.count_likes()
        start_progress = _percent_progress(likes_rows_before, self._likes_background_target_items)
        LOGGER.info(
            (
                "youtube likes background_sync start hot_pages=%s backfill_pages=%s "
                "page_size=%s target_items=%s cache_rows=%s progress=%s%%"
            ),
            self._likes_background_hot_pages,
            self._likes_background_backfill_pages_per_run,
            self._likes_background_page_size,
            self._likes_background_target_items,
            likes_rows_before,
            start_progress,
        )
        client = _build_youtube_client(self._data_dir)
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
                enrich_metadata=True,
            )
            total_units += page_fetch.estimated_api_units
            hot_pages_processed += 1
            if not page_fetch.videos:
                LOGGER.info(
                    "youtube likes background_sync hot_page=%s empty next_page_token=%s",
                    hot_page_index + 1,
                    bool(page_fetch.next_page_token),
                )
                hot_next_page_token = None
                break

            cached_rows = [_video_to_cached_like(video) for video in page_fetch.videos]
            self._cache_repository.upsert_likes(
                videos=cached_rows,
                max_items=self._likes_background_target_items,
            )
            upserted_rows += len(cached_rows)
            LOGGER.info(
                "youtube likes background_sync hot_page=%s fetched=%s next_page_token=%s",
                hot_page_index + 1,
                len(cached_rows),
                bool(page_fetch.next_page_token),
            )
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
                enrich_metadata=True,
            )
            total_units += page_fetch.estimated_api_units
            backfill_pages_processed += 1
            if page_fetch.videos:
                cached_rows = [_video_to_cached_like(video) for video in page_fetch.videos]
                self._cache_repository.upsert_likes(
                    videos=cached_rows,
                    max_items=self._likes_background_target_items,
                )
                upserted_rows += len(cached_rows)
                LOGGER.info(
                    "youtube likes background_sync backfill_page=%s fetched=%s next_page_token=%s",
                    backfill_page_index + 1,
                    len(cached_rows),
                    bool(page_fetch.next_page_token),
                )
            else:
                LOGGER.info(
                    "youtube likes background_sync backfill_page=%s empty next_page_token=%s",
                    backfill_page_index + 1,
                    bool(page_fetch.next_page_token),
                )

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

        self._cache_repository.trim_likes(max_items=self._likes_background_target_items)
        self._mark_background_sync_run()
        likes_rows_after = self._cache_repository.count_likes()
        end_progress = _percent_progress(likes_rows_after, self._likes_background_target_items)
        LOGGER.info(
            (
                "youtube likes background_sync done upserted=%s units=%s hot_pages=%s "
                "backfill_pages=%s backfill_token_set=%s cache_rows_before=%s "
                "cache_rows_after=%s progress=%s%%"
            ),
            upserted_rows,
            total_units,
            hot_pages_processed,
            backfill_pages_processed,
            backfill_page_token is not None,
            likes_rows_before,
            likes_rows_after,
            end_progress,
        )

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
        self._cache_repository.clear_cache_state_value(
            key=LIKES_RECENT_PROBE_RATE_LIMIT_STREAK_KEY
        )

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
        if self._cache_repository is None or self._mode != "oauth":
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
            client = _build_youtube_client(self._data_dir)
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
                    enrich_metadata=enrich_metadata,
                )
                estimated_units += page_fetch.estimated_api_units
                pages_used += 1
                fetched_videos.extend(page_fetch.videos)
                next_page_token = page_fetch.next_page_token
                if next_page_token is None:
                    break

            if fetched_videos:
                cache_rows = [_video_to_cached_like(video) for video in fetched_videos]
                self._cache_repository.upsert_likes(
                    videos=cache_rows,
                    max_items=max(self._likes_cache_max_items, self._likes_background_target_items),
                )

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
        if (
            self._mode != "oauth"
            or not self._transcript_background_sync_enabled
            or self._cache_repository is None
        ):
            return

        if not self._transcript_background_interval_elapsed():
            return

        now = datetime.now(UTC)
        pause_until = self._transcript_global_pause_until(now)
        if pause_until is not None:
            self._mark_transcript_background_run()
            remaining_seconds = max(0, int((pause_until - now).total_seconds()))
            ip_block_streak = self._current_transcript_ip_block_streak()
            LOGGER.warning(
                (
                    "youtube transcript background_sync skip reason=ip_block_pause "
                    "remaining_seconds=%s ip_block_streak=%s"
                ),
                remaining_seconds,
                ip_block_streak,
            )
            return

        likes_rows = self._cache_repository.count_likes()
        transcript_rows_before = self._cache_repository.count_transcripts()
        coverage_before = _percent_progress(transcript_rows_before, likes_rows)
        status_counts_before = self._cache_repository.count_transcript_sync_state_by_status()

        candidate = self._cache_repository.get_next_transcript_candidate(
            recent_limit=self._transcript_background_recent_limit,
            not_before=now,
        )
        if candidate is None:
            self._mark_transcript_background_run()
            LOGGER.info(
                (
                    "youtube transcript background_sync skip reason=no_candidate recent_limit=%s "
                    "likes_rows=%s transcript_rows=%s coverage=%s%% done=%s retry_wait=%s"
                ),
                self._transcript_background_recent_limit,
                likes_rows,
                transcript_rows_before,
                coverage_before,
                status_counts_before.get("done", 0),
                status_counts_before.get("retry_wait", 0),
            )
            return

        LOGGER.info(
            (
                "youtube transcript background_sync start video_id=%s liked_at=%s "
                "likes_rows=%s transcript_rows=%s coverage=%s%% done=%s retry_wait=%s"
            ),
            candidate.video_id,
            candidate.liked_at,
            likes_rows,
            transcript_rows_before,
            coverage_before,
            status_counts_before.get("done", 0),
            status_counts_before.get("retry_wait", 0),
        )
        try:
            transcript_result = self.get_transcript_with_metadata(candidate.video_id)
        except Exception as exc:
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
                error=str(exc),
            )
            self._mark_transcript_background_run()
            status_counts_after = self._cache_repository.count_transcript_sync_state_by_status()
            LOGGER.warning(
                (
                    "youtube transcript background_sync failed video_id=%s attempts=%s "
                    "backoff_seconds=%s ip_blocked=%s ip_block_streak=%s done=%s retry_wait=%s"
                ),
                candidate.video_id,
                attempts,
                backoff_seconds,
                ip_blocked,
                ip_block_streak,
                status_counts_after.get("done", 0),
                status_counts_after.get("retry_wait", 0),
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
                "youtube transcript background_sync done video_id=%s cache_hit=%s source=%s "
                "transcript_rows_before=%s transcript_rows_after=%s coverage=%s%% "
                "done=%s retry_wait=%s"
            ),
            candidate.video_id,
            transcript_result.cache_hit,
            transcript_result.transcript.source,
            transcript_rows_before,
            transcript_rows_after,
            coverage_after,
            status_counts_after.get("done", 0),
            status_counts_after.get("retry_wait", 0),
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

    def search_recent_content_with_metadata(
        self,
        *,
        query: str,
        window_days: int,
        limit: int,
        probe_recent_on_miss: bool,
        recent_probe_pages: int,
    ) -> YouTubeRecentContentSearchResult:
        normalized_limit = max(1, min(25, limit))
        normalized_window_days = max(1, min(30, window_days))
        normalized_query = query.strip()
        if not normalized_query:
            raise YouTubeServiceError("payload.query is required")

        cutoff = datetime.now(UTC) - timedelta(days=normalized_window_days)
        estimated_api_units = 0
        recent_probe_applied = False
        recent_probe_pages_used = 0

        if self._mode != "oauth":
            matches, recent_count, transcript_count = _search_fixture_recent_content(
                query=normalized_query,
                cutoff=cutoff,
            )
            return YouTubeRecentContentSearchResult(
                matches=matches[:normalized_limit],
                recent_videos_count=recent_count,
                transcripts_available_count=transcript_count,
                transcript_coverage_percent=_percent_progress(transcript_count, recent_count),
                estimated_api_units=0,
                cache_miss=not matches,
                recent_probe_applied=False,
                recent_probe_pages_used=0,
            )

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
        LOGGER.info(
            (
                "youtube recent_content_search query=%s window_days=%s matches=%s "
                "recent_videos=%s transcripts_available=%s cache_miss=%s probe_applied=%s "
                "probe_pages=%s"
            ),
            normalized_query,
            normalized_window_days,
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
        cutoff: datetime,
    ) -> tuple[list[YouTubeRecentContentMatch], list[YouTubeVideo], dict[str, str]]:
        if self._cache_repository is None:
            return [], [], {}

        cached_rows = self._cache_repository.list_likes(
            limit=max(self._likes_cache_max_items, self._likes_background_target_items)
        )
        recent_videos: list[YouTubeVideo] = []
        for row in cached_rows:
            liked_at = _parse_datetime_utc(row.liked_at)
            if liked_at is None or liked_at < cutoff:
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
        probe_recent_on_miss: bool = False,
        recent_probe_pages: int = 1,
    ) -> YouTubeListRecentResult:
        normalized_limit = max(1, min(100, limit))
        if self._mode != "oauth":
            videos = _filter_fixture_videos(limit=normalized_limit, query=query)
            return YouTubeListRecentResult(
                videos=videos,
                estimated_api_units=0,
                cache_hit=False,
                refreshed=False,
                cache_miss=query is not None and not videos,
            )

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

        videos = filtered[:normalized_limit]

        LOGGER.info(
            (
                "youtube likes cache_only query=%s limit=%s rows=%s cache_populated=%s "
                "cache_miss=%s recent_probe_applied=%s recent_probe_pages_used=%s"
            ),
            query,
            normalized_limit,
            len(videos),
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
        )

    def list_recent_with_metadata(
        self, limit: int, query: str | None = None
    ) -> YouTubeListRecentResult:
        normalized_limit = max(1, min(100, limit))
        if self._mode != "oauth":
            return YouTubeListRecentResult(
                videos=_filter_fixture_videos(limit=normalized_limit, query=query),
                estimated_api_units=0,
                cache_hit=False,
                refreshed=False,
            )

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
        if self._mode != "oauth":
            transcript = FIXTURE_TRANSCRIPTS.get(video_id)
            if transcript is None:
                raise YouTubeServiceError(f"No fixture transcript found for video_id={video_id}")
            return YouTubeTranscriptResult(
                transcript=transcript,
                estimated_api_units=0,
                cache_hit=False,
            )

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
            transcript = self._fetch_transcript_with_api(video_id)
        except YouTubeTranscriptIpBlockedError:
            raise
        except Exception as exc:
            raise YouTubeServiceError(f"Failed to fetch YouTube transcript payload: {exc}") from exc
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
                    segments=segments_payload,
                )
                LOGGER.info("youtube transcript cache_store video_id=%s", video_id)

            return YouTubeTranscriptResult(
                transcript=transcript,
                estimated_api_units=1,
                cache_hit=False,
            )

        raise YouTubeServiceError(
            "Transcript unavailable from YouTube captions and no fallback provider succeeded"
        )

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
        if self._cache_repository is not None:
            cached_rows = [_video_to_cached_like(video) for video in oauth_fetch.videos]
            self._cache_repository.replace_likes(
                videos=cached_rows,
                max_items=self._likes_cache_max_items,
            )
        return oauth_fetch

    def _list_recent_oauth(self, limit: int, *, enrich_metadata: bool) -> _OAuthLikedFetch:
        client = _build_youtube_client(self._data_dir)

        try:
            oauth_fetch = _list_from_liked_videos(client, limit, enrich_metadata=enrich_metadata)
        except Exception as exc:
            raise YouTubeServiceError(
                f"Failed to fetch liked videos for OAuth user: {exc}"
            ) from exc

        if not oauth_fetch.videos:
            raise YouTubeServiceError("No liked videos available for this OAuth account.")

        return _OAuthLikedFetch(
            videos=oauth_fetch.videos[:limit],
            estimated_api_units=oauth_fetch.estimated_api_units,
        )

    def _fetch_transcript_with_api(self, video_id: str) -> YouTubeTranscript | None:
        snippet = _fetch_video_snippet(video_id, self._data_dir)
        title = snippet.title

        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            transcript_api = cast(Any, YouTubeTranscriptApi)
            segments_raw = _fetch_captions_segments(video_id, transcript_api)

            text = "\n".join(str(segment.get("text", "")) for segment in segments_raw).strip()
            if text:
                parsed_segments = _normalize_segments(segments_raw)

                return YouTubeTranscript(
                    video_id=video_id,
                    title=title,
                    transcript=text,
                    source="youtube_captions",
                    segments=parsed_segments,
                )
        except Exception as exc:
            if _is_transcript_ip_block_error(exc):
                raise YouTubeTranscriptIpBlockedError(
                    "YouTube transcript endpoint is temporarily blocking this IP "
                    "(IpBlocked/RequestBlocked)."
                ) from exc

        description = snippet.description
        if description is None:
            return None

        return YouTubeTranscript(
            video_id=video_id,
            title=title,
            transcript=description,
            source="video_description_fallback",
            segments=[],
        )


def _search_fixture_recent_content(
    *,
    query: str,
    cutoff: datetime,
) -> tuple[list[YouTubeRecentContentMatch], int, int]:
    recent_videos = [video for video in FIXTURE_VIDEOS if _video_liked_datetime(video) >= cutoff]
    transcript_texts: dict[str, str] = {}
    for video in recent_videos:
        transcript = FIXTURE_TRANSCRIPTS.get(video.video_id)
        if transcript is not None and transcript.transcript.strip():
            transcript_texts[video.video_id] = transcript.transcript

    matches = _search_recent_content_matches(
        query=query,
        videos=recent_videos,
        transcript_texts=transcript_texts,
    )
    return matches, len(recent_videos), len(transcript_texts)


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


def _filter_fixture_videos(limit: int, query: str | None) -> list[YouTubeVideo]:
    if query is None:
        return FIXTURE_VIDEOS[:limit]

    filtered = _filter_videos_by_query(FIXTURE_VIDEOS, query)
    return filtered[:limit]


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
    return any(
        not video.description and not video.channel_title and not video.tags for video in videos
    )


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


def _build_youtube_client(data_dir: Path) -> Any:
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
    token_path, secrets_path = resolve_oauth_paths(data_dir)

    request_cls: Any = requests_module.Request
    credentials_cls: Any = credentials_module.Credentials
    flow_cls: Any = flow_module.InstalledAppFlow
    build_fn: Any = discovery_module.build

    credentials: Any | None = None
    if token_path.exists():
        credentials = credentials_cls.from_authorized_user_file(str(token_path), scope)

    if credentials is None or not credentials.valid:
        if credentials is not None and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(request_cls())
            except Exception as exc:
                LOGGER.warning(
                    "youtube oauth token_refresh_failed token_path=%s",
                    token_path,
                    exc_info=True,
                )
                if _oauth_refresh_requires_reauth(exc):
                    raise YouTubeServiceError(
                        "YouTube OAuth token has expired or was revoked. "
                        f"Remove {token_path} and run `just youtube-auth` to re-authorize."
                    ) from exc
                raise YouTubeServiceError(f"Failed to refresh YouTube OAuth token: {exc}") from exc
        else:
            if not secrets_path.exists():
                raise YouTubeServiceError(f"Missing OAuth client secret file at {secrets_path}")

            flow = flow_cls.from_client_secrets_file(str(secrets_path), scope)
            credentials = flow.run_local_server(port=0)

        if credentials is None:
            raise YouTubeServiceError("OAuth flow did not return credentials")

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(str(credentials.to_json()), encoding="utf-8")

    return build_fn("youtube", "v3", credentials=credentials, cache_discovery=False)


def resolve_oauth_paths(data_dir: Path) -> tuple[Path, Path]:
    token_override = os.getenv("ACTIVE_WORKBENCH_YOUTUBE_TOKEN_PATH")
    secret_override = os.getenv("ACTIVE_WORKBENCH_YOUTUBE_CLIENT_SECRET_PATH")

    token_path = (
        Path(token_override).expanduser().resolve()
        if token_override
        else (data_dir / "youtube-token.json").resolve()
    )
    secrets_path = (
        Path(secret_override).expanduser().resolve()
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


def _fetch_captions_segments(video_id: str, transcript_api_ref: Any) -> list[dict[str, Any]]:
    preferred_languages = list(PREFERRED_TRANSCRIPT_LANGUAGES)
    api_instance = _build_transcript_api_instance(transcript_api_ref)

    fetch_callable = getattr(api_instance, "fetch", None)
    if callable(fetch_callable):
        try:
            fetched = fetch_callable(
                video_id,
                languages=preferred_languages,
                preserve_formatting=False,
            )
            segments = _normalize_segments(fetched)
            if segments:
                return segments
        except Exception as exc:
            if _is_transcript_ip_block_error(exc):
                raise

    list_callable = getattr(api_instance, "list", None)
    if callable(list_callable):
        try:
            transcript_list = list_callable(video_id)
            selected = _select_transcript_track(transcript_list, preferred_languages)
            if selected is not None:
                track_fetch = getattr(selected, "fetch", None)
                if callable(track_fetch):
                    fetched = track_fetch()
                    segments = _normalize_segments(fetched)
                    if segments:
                        return segments
        except Exception as exc:
            if _is_transcript_ip_block_error(exc):
                raise

    legacy_get = getattr(transcript_api_ref, "get_transcript", None)
    if callable(legacy_get):
        try:
            legacy_segments = legacy_get(video_id, languages=preferred_languages)
            return _normalize_segments(legacy_segments)
        except Exception as exc:
            if _is_transcript_ip_block_error(exc):
                raise

    legacy_get_instance = getattr(api_instance, "get_transcript", None)
    if callable(legacy_get_instance):
        try:
            legacy_segments = legacy_get_instance(video_id, languages=preferred_languages)
            return _normalize_segments(legacy_segments)
        except Exception as exc:
            if _is_transcript_ip_block_error(exc):
                raise

    return []


def _build_transcript_api_instance(transcript_api_ref: Any) -> Any:
    try:
        return transcript_api_ref()
    except Exception:
        return transcript_api_ref


def _select_transcript_track(transcript_list: Any, preferred_languages: list[str]) -> Any | None:
    for selector_name in (
        "find_manually_created_transcript",
        "find_generated_transcript",
        "find_transcript",
    ):
        selector = getattr(transcript_list, selector_name, None)
        if callable(selector):
            try:
                track = selector(preferred_languages)
                if track is not None:
                    return track
            except Exception:
                continue

    try:
        for track in transcript_list:
            return track
    except Exception:
        return None

    return None


def _normalize_segments(raw_segments: Any) -> list[dict[str, Any]]:
    to_raw_data = getattr(raw_segments, "to_raw_data", None)
    if callable(to_raw_data):
        raw_segments = to_raw_data()

    segments: list[dict[str, Any]] = []
    for raw_segment in _iterable_items(raw_segments):
        segment_dict = _segment_to_dict(raw_segment)
        if segment_dict is not None:
            segments.append(segment_dict)
    return segments


def _iterable_items(raw_value: Any) -> list[Any]:
    if isinstance(raw_value, list):
        raw_list = cast(list[Any], raw_value)
        return list(raw_list)
    if isinstance(raw_value, tuple):
        raw_tuple = cast(tuple[Any, ...], raw_value)
        return list(raw_tuple)

    try:
        iterator: Any = iter(raw_value)
    except Exception:
        return []

    items: list[Any] = []
    for item in iterator:
        items.append(item)
    return items


def _segment_to_dict(raw_segment: Any) -> dict[str, Any] | None:
    if isinstance(raw_segment, dict):
        source = cast(dict[object, object], raw_segment)
        text = source.get("text")
        start = source.get("start")
        duration = source.get("duration")
    else:
        text = getattr(raw_segment, "text", None)
        start = getattr(raw_segment, "start", None)
        duration = getattr(raw_segment, "duration", None)

    if not isinstance(text, str):
        return None

    return {
        "text": text,
        "start": _coerce_float(start),
        "duration": _coerce_float(duration),
    }


def _coerce_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _fetch_video_snippet(video_id: str, data_dir: Path) -> _VideoSnippet:
    client = _build_youtube_client(data_dir)
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
