from __future__ import annotations

from functools import lru_cache

from backend.app.config import AppSettings, load_settings
from backend.app.repositories.audit_repository import AuditRepository
from backend.app.repositories.database import Database
from backend.app.repositories.idempotency_repository import IdempotencyRepository
from backend.app.repositories.jobs_repository import JobsRepository
from backend.app.repositories.memory_repository import MemoryRepository
from backend.app.repositories.vault_repository import VaultRepository
from backend.app.repositories.youtube_cache_repository import YouTubeCacheRepository
from backend.app.repositories.youtube_quota_repository import YouTubeQuotaRepository
from backend.app.services.tool_dispatcher import ToolDispatcher
from backend.app.services.youtube_service import YouTubeService


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
        ),
        default_timezone=settings.default_timezone,
        youtube_daily_quota_limit=settings.youtube_daily_quota_limit,
        youtube_quota_warning_percent=settings.youtube_quota_warning_percent,
    )


def reset_cached_dependencies() -> None:
    get_dispatcher.cache_clear()
    get_settings.cache_clear()
