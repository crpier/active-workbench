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


def test_load_settings_parses_bool_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "false")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "fixture")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_DAILY_QUOTA_LIMIT", "12000")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_QUOTA_WARNING_PERCENT", "0.75")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_LIKES_CACHE_TTL_SECONDS", "120")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_LIKES_RECENT_GUARD_SECONDS", "15")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_LIKES_CACHE_MAX_ITEMS", "250")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_CACHE_TTL_SECONDS", "1800")
    monkeypatch.setenv("ACTIVE_WORKBENCH_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ACTIVE_WORKBENCH_LOG_MAX_BYTES", "2048")
    monkeypatch.setenv("ACTIVE_WORKBENCH_LOG_BACKUP_COUNT", "3")

    settings = load_settings()
    assert settings.data_dir == (tmp_path / "data").resolve()
    assert settings.scheduler_enabled is False
    assert settings.youtube_mode == "fixture"
    assert settings.youtube_daily_quota_limit == 12_000
    assert settings.youtube_quota_warning_percent == 0.75
    assert settings.youtube_likes_cache_ttl_seconds == 120
    assert settings.youtube_likes_recent_guard_seconds == 15
    assert settings.youtube_likes_cache_max_items == 250
    assert settings.youtube_transcript_cache_ttl_seconds == 1800
    assert settings.log_dir == (tmp_path / "data" / "logs").resolve()
    assert settings.log_level == "DEBUG"
    assert settings.log_max_bytes == 2048
    assert settings.log_backup_count == 3
