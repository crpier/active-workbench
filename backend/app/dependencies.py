from __future__ import annotations

from functools import lru_cache

from backend.app.config import AppSettings, load_settings
from backend.app.repositories.audit_repository import AuditRepository
from backend.app.repositories.bucket_bookwyrm_quota_repository import (
    BucketBookwyrmQuotaRepository,
)
from backend.app.repositories.bucket_musicbrainz_quota_repository import (
    BucketMusicbrainzQuotaRepository,
)
from backend.app.repositories.bucket_repository import BucketRepository
from backend.app.repositories.bucket_tmdb_quota_repository import BucketTmdbQuotaRepository
from backend.app.repositories.database import Database
from backend.app.repositories.idempotency_repository import IdempotencyRepository
from backend.app.repositories.jobs_repository import JobsRepository
from backend.app.repositories.memory_repository import MemoryRepository
from backend.app.repositories.vault_repository import VaultRepository
from backend.app.repositories.youtube_cache_repository import YouTubeCacheRepository
from backend.app.repositories.youtube_quota_repository import YouTubeQuotaRepository
from backend.app.services.bucket_metadata_service import BucketMetadataService
from backend.app.services.tool_dispatcher import ToolDispatcher
from backend.app.services.youtube_service import YouTubeService
from backend.app.telemetry import TelemetryClient, build_telemetry_client


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return load_settings()


@lru_cache(maxsize=1)
def get_dispatcher() -> ToolDispatcher:
    settings = get_settings()
    database = Database(settings.db_path)
    database.initialize()

    return ToolDispatcher(
        audit_repository=AuditRepository(database),
        idempotency_repository=IdempotencyRepository(database),
        memory_repository=MemoryRepository(database),
        jobs_repository=JobsRepository(database),
        vault_repository=VaultRepository(settings.vault_dir),
        bucket_repository=BucketRepository(database),
        bucket_metadata_service=BucketMetadataService(
            enrichment_enabled=settings.bucket_enrichment_enabled,
            http_timeout_seconds=settings.bucket_enrichment_http_timeout_seconds,
            tmdb_api_key=settings.bucket_tmdb_api_key,
            tmdb_quota_repository=BucketTmdbQuotaRepository(database),
            tmdb_daily_soft_limit=settings.bucket_tmdb_daily_soft_limit,
            tmdb_min_interval_seconds=settings.bucket_tmdb_min_interval_seconds,
            bookwyrm_base_url=settings.bucket_bookwyrm_base_url,
            bookwyrm_user_agent=settings.bucket_bookwyrm_user_agent,
            bookwyrm_quota_repository=BucketBookwyrmQuotaRepository(database),
            bookwyrm_daily_soft_limit=settings.bucket_bookwyrm_daily_soft_limit,
            bookwyrm_min_interval_seconds=settings.bucket_bookwyrm_min_interval_seconds,
            musicbrainz_base_url=settings.bucket_musicbrainz_base_url,
            musicbrainz_user_agent=settings.bucket_musicbrainz_user_agent,
            musicbrainz_quota_repository=BucketMusicbrainzQuotaRepository(database),
            musicbrainz_daily_soft_limit=settings.bucket_musicbrainz_daily_soft_limit,
            musicbrainz_min_interval_seconds=settings.bucket_musicbrainz_min_interval_seconds,
        ),
        youtube_quota_repository=YouTubeQuotaRepository(database),
        youtube_service=YouTubeService(
            settings.youtube_mode,
            settings.data_dir,
            cache_repository=YouTubeCacheRepository(database),
            likes_cache_ttl_seconds=settings.youtube_likes_cache_ttl_seconds,
            likes_recent_guard_seconds=settings.youtube_likes_recent_guard_seconds,
            likes_cache_max_items=settings.youtube_likes_cache_max_items,
            likes_background_sync_enabled=settings.youtube_background_sync_enabled,
            likes_background_min_interval_seconds=settings.youtube_background_min_interval_seconds,
            likes_background_hot_pages=settings.youtube_background_hot_pages,
            likes_background_backfill_pages_per_run=(
                settings.youtube_background_backfill_pages_per_run
            ),
            likes_background_page_size=settings.youtube_background_page_size,
            likes_background_target_items=settings.youtube_background_target_items,
            transcript_cache_ttl_seconds=settings.youtube_transcript_cache_ttl_seconds,
            transcript_background_sync_enabled=(
                settings.youtube_transcript_background_sync_enabled
            ),
            transcript_background_min_interval_seconds=(
                settings.youtube_transcript_background_min_interval_seconds
            ),
            transcript_background_recent_limit=settings.youtube_transcript_background_recent_limit,
            transcript_background_backoff_base_seconds=(
                settings.youtube_transcript_background_backoff_base_seconds
            ),
            transcript_background_backoff_max_seconds=(
                settings.youtube_transcript_background_backoff_max_seconds
            ),
            transcript_background_ip_block_pause_seconds=(
                settings.youtube_transcript_background_ip_block_pause_seconds
            ),
            oauth_token_path=settings.youtube_token_path,
            oauth_client_secret_path=settings.youtube_client_secret_path,
            supadata_api_key=settings.supadata_api_key,
            supadata_base_url=settings.supadata_base_url,
            supadata_transcript_mode=settings.supadata_transcript_mode,
            supadata_http_timeout_seconds=settings.supadata_http_timeout_seconds,
            supadata_poll_interval_seconds=settings.supadata_poll_interval_seconds,
            supadata_poll_max_attempts=settings.supadata_poll_max_attempts,
        ),
        default_timezone=settings.default_timezone,
        youtube_daily_quota_limit=settings.youtube_daily_quota_limit,
        youtube_quota_warning_percent=settings.youtube_quota_warning_percent,
        telemetry=get_telemetry(),
    )


@lru_cache(maxsize=1)
def get_telemetry() -> TelemetryClient:
    settings = get_settings()
    return build_telemetry_client(
        enabled=settings.telemetry_enabled,
        sink=settings.telemetry_sink,
    )


def reset_cached_dependencies() -> None:
    get_dispatcher.cache_clear()
    get_telemetry.cache_clear()
    get_settings.cache_clear()
