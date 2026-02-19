from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    data_dir: Path
    vault_dir: Path
    db_path: Path
    default_timezone: str
    youtube_mode: str
    scheduler_enabled: bool
    scheduler_poll_interval_seconds: int
    youtube_daily_quota_limit: int
    youtube_quota_warning_percent: float
    youtube_likes_cache_ttl_seconds: int
    youtube_likes_recent_guard_seconds: int
    youtube_likes_cache_max_items: int
    youtube_background_sync_enabled: bool
    youtube_background_min_interval_seconds: int
    youtube_background_hot_pages: int
    youtube_background_backfill_pages_per_run: int
    youtube_background_page_size: int
    youtube_background_target_items: int
    youtube_transcript_cache_ttl_seconds: int
    youtube_transcript_background_sync_enabled: bool
    youtube_transcript_background_min_interval_seconds: int
    youtube_transcript_background_recent_limit: int
    youtube_transcript_background_backoff_base_seconds: int
    youtube_transcript_background_backoff_max_seconds: int
    youtube_transcript_background_ip_block_pause_seconds: int
    log_dir: Path
    log_level: str
    log_max_bytes: int
    log_backup_count: int


DEFAULT_DATA_DIR = ".active-workbench"


def _env_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def load_settings() -> AppSettings:
    data_dir = Path(os.getenv("ACTIVE_WORKBENCH_DATA_DIR", DEFAULT_DATA_DIR)).resolve()
    vault_dir = Path(os.getenv("ACTIVE_WORKBENCH_VAULT_DIR", str(data_dir / "vault"))).resolve()
    db_path = Path(os.getenv("ACTIVE_WORKBENCH_DB_PATH", str(data_dir / "state.db"))).resolve()
    default_timezone = os.getenv("ACTIVE_WORKBENCH_DEFAULT_TIMEZONE", "Europe/Bucharest")
    youtube_mode = os.getenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "fixture")
    scheduler_enabled = _env_bool(
        os.getenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER"),
        default=True,
    )
    scheduler_poll_interval_seconds = int(
        os.getenv("ACTIVE_WORKBENCH_SCHEDULER_POLL_INTERVAL_SECONDS", "30")
    )
    youtube_daily_quota_limit = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_DAILY_QUOTA_LIMIT", "10000")
    )
    youtube_quota_warning_percent = float(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_QUOTA_WARNING_PERCENT", "0.8")
    )
    youtube_likes_cache_ttl_seconds = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_LIKES_CACHE_TTL_SECONDS", "600")
    )
    youtube_likes_recent_guard_seconds = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_LIKES_RECENT_GUARD_SECONDS", "45")
    )
    youtube_likes_cache_max_items = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_LIKES_CACHE_MAX_ITEMS", "500")
    )
    youtube_background_sync_enabled = _env_bool(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_SYNC_ENABLED"),
        default=True,
    )
    youtube_background_min_interval_seconds = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_MIN_INTERVAL_SECONDS", "120")
    )
    youtube_background_hot_pages = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_HOT_PAGES", "2")
    )
    youtube_background_backfill_pages_per_run = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_BACKFILL_PAGES_PER_RUN", "1")
    )
    youtube_background_page_size = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_PAGE_SIZE", "50")
    )
    youtube_background_target_items = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_TARGET_ITEMS", "1000")
    )
    youtube_transcript_cache_ttl_seconds = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_CACHE_TTL_SECONDS", "86400")
    )
    youtube_transcript_background_sync_enabled = _env_bool(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_SYNC_ENABLED"),
        default=True,
    )
    youtube_transcript_background_min_interval_seconds = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_MIN_INTERVAL_SECONDS", "20")
    )
    youtube_transcript_background_recent_limit = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_RECENT_LIMIT", "1000")
    )
    youtube_transcript_background_backoff_base_seconds = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_BACKOFF_BASE_SECONDS", "300")
    )
    youtube_transcript_background_backoff_max_seconds = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_BACKOFF_MAX_SECONDS", "86400")
    )
    youtube_transcript_background_ip_block_pause_seconds = int(
        os.getenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_IP_BLOCK_PAUSE_SECONDS", "7200")
    )
    log_dir = Path(os.getenv("ACTIVE_WORKBENCH_LOG_DIR", str(data_dir / "logs"))).resolve()
    log_level = os.getenv("ACTIVE_WORKBENCH_LOG_LEVEL", "INFO")
    log_max_bytes = int(os.getenv("ACTIVE_WORKBENCH_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    log_backup_count = int(os.getenv("ACTIVE_WORKBENCH_LOG_BACKUP_COUNT", "5"))

    return AppSettings(
        data_dir=data_dir,
        vault_dir=vault_dir,
        db_path=db_path,
        default_timezone=default_timezone,
        youtube_mode=youtube_mode,
        scheduler_enabled=scheduler_enabled,
        scheduler_poll_interval_seconds=scheduler_poll_interval_seconds,
        youtube_daily_quota_limit=youtube_daily_quota_limit,
        youtube_quota_warning_percent=youtube_quota_warning_percent,
        youtube_likes_cache_ttl_seconds=youtube_likes_cache_ttl_seconds,
        youtube_likes_recent_guard_seconds=youtube_likes_recent_guard_seconds,
        youtube_likes_cache_max_items=youtube_likes_cache_max_items,
        youtube_background_sync_enabled=youtube_background_sync_enabled,
        youtube_background_min_interval_seconds=youtube_background_min_interval_seconds,
        youtube_background_hot_pages=youtube_background_hot_pages,
        youtube_background_backfill_pages_per_run=youtube_background_backfill_pages_per_run,
        youtube_background_page_size=youtube_background_page_size,
        youtube_background_target_items=youtube_background_target_items,
        youtube_transcript_cache_ttl_seconds=youtube_transcript_cache_ttl_seconds,
        youtube_transcript_background_sync_enabled=youtube_transcript_background_sync_enabled,
        youtube_transcript_background_min_interval_seconds=(
            youtube_transcript_background_min_interval_seconds
        ),
        youtube_transcript_background_recent_limit=youtube_transcript_background_recent_limit,
        youtube_transcript_background_backoff_base_seconds=(
            youtube_transcript_background_backoff_base_seconds
        ),
        youtube_transcript_background_backoff_max_seconds=(
            youtube_transcript_background_backoff_max_seconds
        ),
        youtube_transcript_background_ip_block_pause_seconds=(
            youtube_transcript_background_ip_block_pause_seconds
        ),
        log_dir=log_dir,
        log_level=log_level,
        log_max_bytes=log_max_bytes,
        log_backup_count=log_backup_count,
    )
