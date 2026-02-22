from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATA_DIR = ".active-workbench"
YOUTUBE_MODES: frozenset[str] = frozenset({"oauth"})
_DATA_DIR_RELATIVE_DEFAULTS: tuple[tuple[str, Path], ...] = (
    ("vault_dir", Path("vault")),
    ("db_path", Path("state.db")),
    ("youtube_token_path", Path("youtube-token.json")),
    ("youtube_client_secret_path", Path("youtube-client-secret.json")),
    ("log_dir", Path("logs")),
)
_PATH_FIELDS: tuple[str, ...] = (
    "data_dir",
    *(field_name for field_name, _ in _DATA_DIR_RELATIVE_DEFAULTS),
)
_BOOLEAN_COERCION_FIELDS: tuple[str, ...] = (
    "scheduler_enabled",
    "youtube_background_sync_enabled",
    "youtube_transcript_background_sync_enabled",
    "bucket_enrichment_enabled",
    "telemetry_enabled",
)


def _default_in_data_dir(relative_path: Path) -> Path:
    return Path(DEFAULT_DATA_DIR) / relative_path


def _data_dir_default_note(relative_path: Path) -> str:
    return f"Defaults to `${{ACTIVE_WORKBENCH_DATA_DIR}}/{relative_path}` when not explicitly set."


def _resolve_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _parse_bool_with_default(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value == 1:
            return True
        if value == 0:
            return False
        return default
    if not isinstance(value, str):
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized:
        return normalized
    return None


class AppSettings(BaseSettings):
    """
    Canonical runtime configuration.

    This class is the single source of truth for config options:
    - what each option controls,
    - where it comes from (`ACTIVE_WORKBENCH_*`),
    - and what its default is.
    """

    model_config = SettingsConfigDict(
        env_prefix="ACTIVE_WORKBENCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # Core paths and mode.
    data_dir: Path = Field(
        default=Path(DEFAULT_DATA_DIR),
        description="Root runtime directory for local state, logs, and OAuth artifacts.",
    )
    vault_dir: Path = Field(
        default=_default_in_data_dir(Path("vault")),
        description=f"Directory for vault data. {_data_dir_default_note(Path('vault'))}",
    )
    db_path: Path = Field(
        default=_default_in_data_dir(Path("state.db")),
        description=f"SQLite database path. {_data_dir_default_note(Path('state.db'))}",
    )
    default_timezone: str = Field(
        default="Europe/Bucharest",
        description="Default timezone used for scheduled jobs and date interpretation.",
    )
    youtube_mode: Literal["oauth"] = Field(
        default="oauth",
        description="YouTube runtime mode. Only OAuth-backed production mode is supported.",
    )

    # Scheduler and quota guardrails.
    scheduler_enabled: bool = Field(
        default=True,
        validation_alias="ACTIVE_WORKBENCH_ENABLE_SCHEDULER",
        description=(
            "Enable background scheduler loop. Uses ACTIVE_WORKBENCH_ENABLE_SCHEDULER "
            "for backward-compatible env naming."
        ),
    )
    scheduler_poll_interval_seconds: int = Field(
        default=60,
        description="Main scheduler polling cadence (jobs + likes background loop).",
    )
    youtube_transcript_scheduler_poll_interval_seconds: int = Field(
        default=20,
        description="Transcript background loop cadence, independent from likes cadence.",
    )
    youtube_daily_quota_limit: int = Field(
        default=10_000,
        description="Expected daily YouTube Data API quota budget used for warnings.",
    )
    youtube_quota_warning_percent: float = Field(
        default=0.8,
        description="Warn when estimated daily usage exceeds this fraction of quota limit.",
    )

    # Likes cache and background sync behavior.
    youtube_likes_cache_ttl_seconds: int = Field(
        default=600,
        description="TTL for liked-video cache freshness checks.",
    )
    youtube_likes_recent_guard_seconds: int = Field(
        default=45,
        description="Fresh-cache guard window for recency-sensitive likes queries.",
    )
    youtube_likes_cache_max_items: int = Field(
        default=500,
        description="Maximum liked videos retained in cache.",
    )
    youtube_background_sync_enabled: bool = Field(
        default=True,
        description="Enable background liked-videos cache synchronization.",
    )
    youtube_background_min_interval_seconds: int = Field(
        default=600,
        description="Minimum time between liked-videos background sync runs.",
    )
    youtube_background_hot_pages: int = Field(
        default=2,
        description="Number of newest likes pages fetched every background run.",
    )
    youtube_background_backfill_pages_per_run: int = Field(
        default=1,
        description="Additional older likes pages fetched per run for cache backfill.",
    )
    youtube_background_page_size: int = Field(
        default=50,
        description="Page size for likes background fetching (capped by YouTube API).",
    )
    youtube_likes_cutoff_date: date = Field(
        default=date(2024, 10, 20),
        description=(
            "Inclusive UTC liked-at date cutoff for cached liked videos and transcript sync scope. "
            "Videos liked before this date are purged from likes/transcript cache."
        ),
    )
    youtube_background_target_items: int = Field(
        default=1_000,
        description="Deprecated sizing hint used by some refresh paths; likes cache retention is cutoff-based.",
    )

    # Transcript cache and background sync behavior.
    youtube_transcript_cache_ttl_seconds: int = Field(
        default=86_400,
        description="TTL for transcript cache freshness.",
    )
    youtube_transcript_background_sync_enabled: bool = Field(
        default=True,
        description="Enable background transcript prefetching for cached liked videos.",
    )
    youtube_transcript_background_min_interval_seconds: int = Field(
        default=20,
        description="Minimum time between transcript background sync attempts.",
    )
    youtube_transcript_background_recent_limit: int = Field(
        default=1_000,
        description="Deprecated transcript scope knob; transcript sync scope now follows the likes-cache cutoff.",
    )
    youtube_transcript_background_backoff_base_seconds: int = Field(
        default=300,
        description="Base exponential backoff for transcript sync failures.",
    )
    youtube_transcript_background_backoff_max_seconds: int = Field(
        default=86_400,
        description="Maximum backoff for transcript sync retries.",
    )
    youtube_transcript_background_ip_block_pause_seconds: int = Field(
        default=7_200,
        description="Global pause baseline when transcript sync IP-block errors are detected.",
    )

    # OAuth and Supadata transcript provider settings.
    youtube_token_path: Path = Field(
        default=_default_in_data_dir(Path("youtube-token.json")),
        description=(
            "OAuth token JSON path. "
            f"{_data_dir_default_note(Path('youtube-token.json'))}"
        ),
    )
    youtube_client_secret_path: Path = Field(
        default=_default_in_data_dir(Path("youtube-client-secret.json")),
        description=(
            "OAuth client secret JSON path. "
            f"{_data_dir_default_note(Path('youtube-client-secret.json'))}"
        ),
    )
    supadata_api_key: str | None = Field(
        default=None,
        description="Supadata API key for OAuth transcript retrieval.",
    )
    supadata_base_url: str = Field(
        default="https://api.supadata.ai/v1",
        description="Supadata API base URL.",
    )
    supadata_transcript_mode: str = Field(
        default="native",
        description="Supadata transcript mode passed to transcript requests.",
    )
    supadata_http_timeout_seconds: float = Field(
        default=30.0,
        description="HTTP timeout for Supadata requests.",
    )
    supadata_poll_interval_seconds: float = Field(
        default=1.0,
        description="Polling interval for async Supadata transcript jobs.",
    )
    supadata_poll_max_attempts: int = Field(
        default=30,
        description="Maximum polling attempts for async Supadata transcript jobs.",
    )

    # Bucket enrichment.
    bucket_enrichment_enabled: bool = Field(
        default=True,
        description="Enable optional metadata enrichment for bucket items.",
    )
    bucket_enrichment_http_timeout_seconds: float = Field(
        default=2.0,
        description="HTTP timeout for bucket metadata enrichment calls.",
    )
    bucket_tmdb_api_key: str | None = Field(
        default=None,
        description="TMDb API key used by bucket enrichment providers.",
    )
    bucket_tmdb_daily_soft_limit: int = Field(
        default=500,
        description="Soft limit for TMDb enrichment calls per UTC day.",
    )
    bucket_tmdb_min_interval_seconds: float = Field(
        default=1.1,
        description="Minimum interval between TMDb enrichment calls to prevent bursts.",
    )
    bucket_bookwyrm_base_url: str = Field(
        default="https://bookwyrm.social",
        description="BookWyrm base URL used for book metadata enrichment.",
    )
    bucket_bookwyrm_user_agent: str = Field(
        default="active-workbench/0.1 (+https://github.com/crpier/active-workbench)",
        description=(
            "User-Agent sent to BookWyrm APIs for identification "
            "(include app name and a contact URL/email)."
        ),
    )
    bucket_bookwyrm_daily_soft_limit: int = Field(
        default=500,
        description="Soft limit for BookWyrm enrichment calls per UTC day.",
    )
    bucket_bookwyrm_min_interval_seconds: float = Field(
        default=1.1,
        description="Minimum interval between BookWyrm enrichment calls to prevent bursts.",
    )
    bucket_musicbrainz_base_url: str = Field(
        default="https://musicbrainz.org",
        description="MusicBrainz base URL used for music album metadata enrichment.",
    )
    bucket_musicbrainz_user_agent: str = Field(
        default="active-workbench/0.1 (+https://github.com/crpier/active-workbench)",
        description=(
            "User-Agent sent to MusicBrainz APIs for identification "
            "(include app name and a contact URL/email)."
        ),
    )
    bucket_musicbrainz_daily_soft_limit: int = Field(
        default=500,
        description="Soft limit for MusicBrainz enrichment calls per UTC day.",
    )
    bucket_musicbrainz_min_interval_seconds: float = Field(
        default=1.1,
        description="Minimum interval between MusicBrainz enrichment calls to prevent bursts.",
    )

    # Logging.
    log_dir: Path = Field(
        default=_default_in_data_dir(Path("logs")),
        description=f"Directory for backend log files. {_data_dir_default_note(Path('logs'))}",
    )
    log_level: str = Field(
        default="INFO",
        description="Console log level (stdout).",
    )
    log_max_bytes: int = Field(
        default=10 * 1024 * 1024,
        description="Legacy compatibility setting for file rotation size (currently unused).",
    )
    log_backup_count: int = Field(
        default=5,
        description="Legacy compatibility setting for rotated file count (currently unused).",
    )

    # Telemetry.
    telemetry_enabled: bool = Field(
        default=True,
        description="Enable lightweight internal telemetry events.",
    )
    telemetry_sink: Literal["none", "log"] = Field(
        default="log",
        description=(
            "Telemetry sink backend. `log` emits structured telemetry locally; "
            "`none` disables sink output."
        ),
    )
    mobile_api_key: str | None = Field(
        default=None,
        description=(
            "Deprecated legacy global bearer token for `/mobile/v1/share/article` "
            "(currently ignored by the mobile share endpoint). "
            "Kept only for compatibility with older deployments/config files."
        ),
    )
    mobile_share_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Mobile share rate-limit window size in seconds.",
    )
    mobile_share_rate_limit_max_requests: int = Field(
        default=30,
        ge=1,
        le=1000,
        description="Maximum mobile share requests allowed per client in each window.",
    )

    @field_validator("youtube_mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("ACTIVE_WORKBENCH_YOUTUBE_MODE must be a string.")

        normalized = value.strip().lower()
        if normalized in YOUTUBE_MODES:
            return normalized

        raise ValueError("ACTIVE_WORKBENCH_YOUTUBE_MODE must be set to: oauth.")

    @field_validator("telemetry_sink", mode="before")
    @classmethod
    def _normalize_telemetry_sink(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("ACTIVE_WORKBENCH_TELEMETRY_SINK must be a string.")
        normalized = value.strip().lower()
        if normalized in {"none", "log"}:
            return normalized
        raise ValueError("ACTIVE_WORKBENCH_TELEMETRY_SINK must be set to: none, log.")

    @field_validator("bucket_bookwyrm_base_url", mode="before")
    @classmethod
    def _normalize_bookwyrm_base_url(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("ACTIVE_WORKBENCH_BUCKET_BOOKWYRM_BASE_URL must be a string.")
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("ACTIVE_WORKBENCH_BUCKET_BOOKWYRM_BASE_URL must not be empty.")
        return normalized

    @field_validator("bucket_bookwyrm_user_agent", mode="before")
    @classmethod
    def _normalize_bookwyrm_user_agent(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("ACTIVE_WORKBENCH_BUCKET_BOOKWYRM_USER_AGENT must be a string.")
        normalized = value.strip()
        if not normalized:
            raise ValueError("ACTIVE_WORKBENCH_BUCKET_BOOKWYRM_USER_AGENT must not be empty.")
        return normalized

    @field_validator("bucket_musicbrainz_base_url", mode="before")
    @classmethod
    def _normalize_musicbrainz_base_url(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_BASE_URL must be a string.")
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_BASE_URL must not be empty.")
        return normalized

    @field_validator("bucket_musicbrainz_user_agent", mode="before")
    @classmethod
    def _normalize_musicbrainz_user_agent(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_USER_AGENT must be a string.")
        normalized = value.strip()
        if not normalized:
            raise ValueError("ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_USER_AGENT must not be empty.")
        return normalized

    @field_validator(*_PATH_FIELDS, mode="before")
    @classmethod
    def _normalize_paths(cls, value: Any) -> Any:
        if value is None:
            return None
        return _resolve_path(value)

    @field_validator(*_BOOLEAN_COERCION_FIELDS, mode="before")
    @classmethod
    def _normalize_booleans(cls, value: Any, info: ValidationInfo) -> bool:
        field_name = info.field_name
        assert field_name is not None
        default_value = cls.model_fields[field_name].default
        assert isinstance(default_value, bool)
        return _parse_bool_with_default(value, default=default_value)

    @field_validator("supadata_api_key", "bucket_tmdb_api_key", "mobile_api_key", mode="before")
    @classmethod
    def _normalize_optional_strings(cls, value: Any) -> str | None:
        return _normalize_optional_text(value)


def _validate_oauth_configuration(
    *,
    youtube_client_secret_path: Path,
    youtube_token_path: Path,
    supadata_api_key: str | None,
    bucket_tmdb_api_key: str | None,
) -> None:
    errors: list[str] = []

    if supadata_api_key is None:
        errors.append(
            "ACTIVE_WORKBENCH_SUPADATA_API_KEY is required for OAuth runtime mode."
        )
    if bucket_tmdb_api_key is None:
        errors.append(
            "ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY is required for bucket enrichment."
        )
    if not youtube_client_secret_path.is_file():
        errors.append(f"Missing OAuth client secret JSON: {youtube_client_secret_path}")
    if not youtube_token_path.is_file():
        errors.append(
            "Missing OAuth token JSON: "
            f"{youtube_token_path} (run `just youtube-auth` or `just youtube-auth-secret ...`)."
        )

    if errors:
        bullets = "\n".join(f"- {message}" for message in errors)
        raise ValueError(
            "Invalid production configuration for OAuth runtime mode:\n"
            f"{bullets}"
        )


def _apply_path_defaults(settings: AppSettings) -> AppSettings:
    updates: dict[str, Path] = {}
    for field_name, relative_default in _DATA_DIR_RELATIVE_DEFAULTS:
        if field_name in settings.model_fields_set:
            continue
        updates[field_name] = settings.data_dir / relative_default
    if not updates:
        return settings
    return settings.model_copy(update=updates)


def _resolve_path_fields(settings: AppSettings) -> AppSettings:
    resolved_updates = {
        field_name: _resolve_path(getattr(settings, field_name))
        for field_name in _PATH_FIELDS
    }
    return settings.model_copy(update=resolved_updates)


def load_settings(*, validate_oauth_secrets: bool = True) -> AppSettings:
    settings = AppSettings()
    settings = _apply_path_defaults(settings)
    settings = _resolve_path_fields(settings)

    if validate_oauth_secrets:
        _validate_oauth_configuration(
            youtube_client_secret_path=settings.youtube_client_secret_path,
            youtube_token_path=settings.youtube_token_path,
            supadata_api_key=settings.supadata_api_key,
            bucket_tmdb_api_key=settings.bucket_tmdb_api_key,
        )

    return settings
