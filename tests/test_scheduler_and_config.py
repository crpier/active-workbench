from __future__ import annotations

import time
from pathlib import Path
from typing import Any, cast

import pytest

from backend.app.config import load_settings
from backend.app.services.scheduler_service import SchedulerService


class _FakeDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    def run_due_jobs(self) -> None:
        self.calls += 1


class _FakeDispatcherWithBucketPoll(_FakeDispatcher):
    def __init__(self) -> None:
        super().__init__()
        self.bucket_annotation_calls = 0

    def run_bucket_annotation_poll(self) -> dict[str, int]:
        self.bucket_annotation_calls += 1
        return {
            "attempted": 0,
            "annotated": 0,
            "pending": 0,
            "failed": 0,
        }


class _FakeYouTubeService:
    def __init__(self) -> None:
        self.likes_calls = 0
        self.transcript_calls = 0

    def run_background_likes_sync(self) -> None:
        self.likes_calls += 1

    def run_background_transcript_sync(self) -> None:
        self.transcript_calls += 1


def test_scheduler_service_runs_jobs() -> None:
    dispatcher = _FakeDispatcher()
    scheduler = SchedulerService(
        dispatcher=cast(Any, dispatcher),
        poll_interval_seconds=1,
    )
    scheduler.start()
    time.sleep(1.2)
    scheduler.stop()
    assert dispatcher.calls >= 1


def test_scheduler_service_throttles_bucket_annotation_poll() -> None:
    dispatcher = _FakeDispatcherWithBucketPoll()
    scheduler = SchedulerService(
        dispatcher=cast(Any, dispatcher),
        poll_interval_seconds=1,
    )
    scheduler.start()
    time.sleep(2.2)
    scheduler.stop()

    assert dispatcher.calls >= 2
    assert dispatcher.bucket_annotation_calls == 1


def test_scheduler_service_decouples_transcript_polling() -> None:
    dispatcher = _FakeDispatcher()
    youtube_service = _FakeYouTubeService()
    scheduler = SchedulerService(
        dispatcher=cast(Any, dispatcher),
        poll_interval_seconds=2,
        transcript_poll_interval_seconds=1,
        youtube_service=cast(Any, youtube_service),
    )
    scheduler.start()
    time.sleep(2.3)
    scheduler.stop()

    assert youtube_service.likes_calls >= 1
    assert youtube_service.transcript_calls >= 2
    assert youtube_service.transcript_calls > youtube_service.likes_calls


def test_load_settings_parses_bool_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "youtube-token.json").write_text("{}", encoding="utf-8")
    (data_dir / "youtube-client-secret.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "false")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_SCHEDULER_POLL_INTERVAL_SECONDS", "22")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "oauth")
    monkeypatch.setenv("ACTIVE_WORKBENCH_SUPADATA_API_KEY", "test-key")
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY", "test-tmdb-key")
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_TMDB_MIN_INTERVAL_SECONDS", "1.2")
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_BOOKWYRM_BASE_URL", " https://bookwyrm.social/ ")
    monkeypatch.setenv(
        "ACTIVE_WORKBENCH_BUCKET_BOOKWYRM_USER_AGENT",
        " active-workbench-tests/1.0 (+test@example.com) ",
    )
    monkeypatch.setenv(
        "ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_BASE_URL",
        " https://musicbrainz.org/ ",
    )
    monkeypatch.setenv(
        "ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_USER_AGENT",
        " active-workbench-tests/1.0 (+test@example.com) ",
    )
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_MIN_INTERVAL_SECONDS", "1.2")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_DAILY_QUOTA_LIMIT", "12000")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_QUOTA_WARNING_PERCENT", "0.75")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_LIKES_CACHE_TTL_SECONDS", "120")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_LIKES_RECENT_GUARD_SECONDS", "15")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_LIKES_CACHE_MAX_ITEMS", "250")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_SYNC_ENABLED", "true")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_MIN_INTERVAL_SECONDS", "90")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_HOT_PAGES", "3")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_BACKFILL_PAGES_PER_RUN", "2")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_PAGE_SIZE", "40")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_TARGET_ITEMS", "900")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_CACHE_TTL_SECONDS", "1800")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_SYNC_ENABLED", "true")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_MIN_INTERVAL_SECONDS", "35")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_RECENT_LIMIT", "800")
    monkeypatch.setenv(
        "ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_BACKOFF_BASE_SECONDS",
        "120",
    )
    monkeypatch.setenv(
        "ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_BACKOFF_MAX_SECONDS",
        "7200",
    )
    monkeypatch.setenv(
        "ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_IP_BLOCK_PAUSE_SECONDS",
        "1800",
    )
    monkeypatch.setenv("ACTIVE_WORKBENCH_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ACTIVE_WORKBENCH_LOG_MAX_BYTES", "2048")
    monkeypatch.setenv("ACTIVE_WORKBENCH_LOG_BACKUP_COUNT", "3")
    monkeypatch.setenv("ACTIVE_WORKBENCH_TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("ACTIVE_WORKBENCH_TELEMETRY_SINK", "log")

    settings = load_settings()
    assert settings.data_dir == (tmp_path / "data").resolve()
    assert settings.scheduler_enabled is False
    assert settings.youtube_transcript_scheduler_poll_interval_seconds == 22
    assert settings.youtube_mode == "oauth"
    assert settings.bucket_tmdb_min_interval_seconds == 1.2
    assert settings.bucket_bookwyrm_base_url == "https://bookwyrm.social"
    assert settings.bucket_bookwyrm_user_agent == "active-workbench-tests/1.0 (+test@example.com)"
    assert settings.bucket_musicbrainz_base_url == "https://musicbrainz.org"
    assert settings.bucket_musicbrainz_user_agent == (
        "active-workbench-tests/1.0 (+test@example.com)"
    )
    assert settings.bucket_musicbrainz_min_interval_seconds == 1.2
    assert settings.youtube_daily_quota_limit == 12_000
    assert settings.youtube_quota_warning_percent == 0.75
    assert settings.youtube_likes_cache_ttl_seconds == 120
    assert settings.youtube_likes_recent_guard_seconds == 15
    assert settings.youtube_likes_cache_max_items == 250
    assert settings.youtube_background_sync_enabled is True
    assert settings.youtube_background_min_interval_seconds == 90
    assert settings.youtube_background_hot_pages == 3
    assert settings.youtube_background_backfill_pages_per_run == 2
    assert settings.youtube_background_page_size == 40
    assert settings.youtube_background_target_items == 900
    assert settings.youtube_transcript_cache_ttl_seconds == 1800
    assert settings.youtube_transcript_background_sync_enabled is True
    assert settings.youtube_transcript_background_min_interval_seconds == 35
    assert settings.youtube_transcript_background_recent_limit == 800
    assert settings.youtube_transcript_background_backoff_base_seconds == 120
    assert settings.youtube_transcript_background_backoff_max_seconds == 7200
    assert settings.youtube_transcript_background_ip_block_pause_seconds == 1800
    assert settings.log_dir == (tmp_path / "data" / "logs").resolve()
    assert settings.log_level == "DEBUG"
    assert settings.log_max_bytes == 2048
    assert settings.log_backup_count == 3
    assert settings.telemetry_enabled is True
    assert settings.telemetry_sink == "log"


def test_load_settings_rejects_invalid_youtube_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "invalid-mode")

    with pytest.raises(ValueError, match="ACTIVE_WORKBENCH_YOUTUBE_MODE"):
        load_settings()


def test_load_settings_oauth_mode_requires_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "oauth")
    monkeypatch.delenv("ACTIVE_WORKBENCH_SUPADATA_API_KEY", raising=False)

    with pytest.raises(ValueError, match="Invalid production configuration"):
        load_settings()


def test_load_settings_oauth_mode_requires_bucket_tmdb_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "youtube-token.json").write_text("{}", encoding="utf-8")
    (data_dir / "youtube-client-secret.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "oauth")
    monkeypatch.setenv("ACTIVE_WORKBENCH_SUPADATA_API_KEY", "test-key")
    monkeypatch.delenv("ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY", raising=False)

    with pytest.raises(ValueError, match="ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY"):
        load_settings()


def test_load_settings_oauth_mode_succeeds_with_required_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "youtube-token.json").write_text("{}", encoding="utf-8")
    (data_dir / "youtube-client-secret.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "oauth")
    monkeypatch.setenv("ACTIVE_WORKBENCH_SUPADATA_API_KEY", "  test-key  ")
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY", "  test-tmdb-key  ")

    settings = load_settings()
    assert settings.youtube_mode == "oauth"
    assert settings.supadata_api_key == "test-key"
    assert settings.bucket_tmdb_api_key == "test-tmdb-key"


def test_load_settings_reads_dotenv_for_oauth_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "runtime"
    data_dir.mkdir(parents=True)
    (data_dir / "youtube-token.json").write_text("{}", encoding="utf-8")
    (data_dir / "youtube-client-secret.json").write_text("{}", encoding="utf-8")

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ACTIVE_WORKBENCH_YOUTUBE_MODE=oauth",
                "ACTIVE_WORKBENCH_SUPADATA_API_KEY=dotenv-key",
                "ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY=dotenv-tmdb-key",
                f"ACTIVE_WORKBENCH_DATA_DIR={data_dir}",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", raising=False)
    monkeypatch.delenv("ACTIVE_WORKBENCH_SUPADATA_API_KEY", raising=False)
    monkeypatch.delenv("ACTIVE_WORKBENCH_DATA_DIR", raising=False)

    settings = load_settings()
    assert settings.youtube_mode == "oauth"
    assert settings.supadata_api_key == "dotenv-key"
    assert settings.bucket_tmdb_api_key == "dotenv-tmdb-key"
    assert settings.data_dir == data_dir.resolve()
