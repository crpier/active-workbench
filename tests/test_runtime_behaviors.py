from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
import structlog
from fastapi.testclient import TestClient

from backend.app.config import AppSettings, load_settings
from backend.app.logging_config import (
    TELEMETRY_LOG_FILE_NAME,
    _stream_supports_color,  # pyright: ignore[reportPrivateUsage]
    configure_application_logging,
)
from backend.app.main import create_app
from backend.app.repositories.database import Database
from backend.app.repositories.memory_repository import MemoryRepository


def test_config_env_bool_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "youtube-token.json").write_text("{}", encoding="utf-8")
    (data_dir / "youtube-client-secret.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "oauth")
    monkeypatch.setenv("ACTIVE_WORKBENCH_SUPADATA_API_KEY", "test-key")
    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "1")
    enabled = load_settings()
    assert enabled.scheduler_enabled is True
    assert enabled.youtube_token_path == (tmp_path / "data" / "youtube-token.json").resolve()
    assert (
        enabled.youtube_client_secret_path
        == (tmp_path / "data" / "youtube-client-secret.json").resolve()
    )

    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "off")
    disabled = load_settings()
    assert disabled.scheduler_enabled is False

    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "invalid")
    monkeypatch.setenv(
        "ACTIVE_WORKBENCH_YOUTUBE_TOKEN_PATH",
        str(tmp_path / "secrets" / "token.json"),
    )
    monkeypatch.setenv(
        "ACTIVE_WORKBENCH_YOUTUBE_CLIENT_SECRET_PATH",
        str(tmp_path / "secrets" / "client.json"),
    )
    (tmp_path / "secrets").mkdir(parents=True, exist_ok=True)
    (tmp_path / "secrets" / "token.json").write_text("{}", encoding="utf-8")
    (tmp_path / "secrets" / "client.json").write_text("{}", encoding="utf-8")
    fallback = load_settings()
    assert fallback.scheduler_enabled is True
    assert fallback.youtube_token_path == (tmp_path / "secrets" / "token.json").resolve()
    assert fallback.youtube_client_secret_path == (tmp_path / "secrets" / "client.json").resolve()


def test_memory_repository_lists_active_entries(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()

    memory_repo = MemoryRepository(db)
    memory_id, undo_token = memory_repo.create_entry(
        content={"fact": "buy leeks"},
        source_refs=[{"type": "note", "id": "n1"}],
    )

    entries = memory_repo.list_active_entries()
    assert entries and entries[0]["id"] == memory_id

    undone = memory_repo.undo(undo_token)
    assert undone == memory_id
    assert memory_repo.list_active_entries() == []


def test_main_lifespan_starts_and_stops_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDispatcher:
        youtube_service = None

        def run_due_jobs(self) -> None:
            return None

    class FakeScheduler:
        started = False
        stopped = False

        def __init__(
            self,
            dispatcher: FakeDispatcher,
            poll_interval_seconds: int,
            *,
            transcript_poll_interval_seconds: int | None = None,
            youtube_service: object | None = None,
            telemetry: object | None = None,
        ) -> None:
            _ = dispatcher
            _ = poll_interval_seconds
            _ = transcript_poll_interval_seconds
            _ = youtube_service
            _ = telemetry

        def start(self) -> None:
            FakeScheduler.started = True

        def stop(self) -> None:
            FakeScheduler.stopped = True

    settings = AppSettings(
        data_dir=Path("/tmp/data"),
        vault_dir=Path("/tmp/data/vault"),
        db_path=Path("/tmp/data/state.db"),
        default_timezone="Europe/Bucharest",
        youtube_mode="oauth",
        scheduler_enabled=True,
        scheduler_poll_interval_seconds=1,
        youtube_transcript_scheduler_poll_interval_seconds=20,
        youtube_daily_quota_limit=10000,
        youtube_quota_warning_percent=0.8,
        youtube_likes_cache_ttl_seconds=600,
        youtube_likes_recent_guard_seconds=45,
        youtube_likes_cache_max_items=500,
        youtube_background_sync_enabled=True,
        youtube_background_min_interval_seconds=120,
        youtube_background_hot_pages=2,
        youtube_background_backfill_pages_per_run=1,
        youtube_background_page_size=50,
        youtube_background_target_items=1000,
        youtube_transcript_cache_ttl_seconds=86400,
        youtube_transcript_background_sync_enabled=True,
        youtube_transcript_background_min_interval_seconds=20,
        youtube_transcript_background_recent_limit=1000,
        youtube_transcript_background_backoff_base_seconds=300,
        youtube_transcript_background_backoff_max_seconds=86400,
        youtube_transcript_background_ip_block_pause_seconds=3600,
        youtube_token_path=Path("/tmp/data/youtube-token.json"),
        youtube_client_secret_path=Path("/tmp/data/youtube-client-secret.json"),
        supadata_api_key=None,
        supadata_base_url="https://api.supadata.ai/v1",
        supadata_transcript_mode="native",
        supadata_http_timeout_seconds=30.0,
        supadata_poll_interval_seconds=1.0,
        supadata_poll_max_attempts=30,
        bucket_enrichment_enabled=False,
        bucket_enrichment_http_timeout_seconds=2.0,
        bucket_omdb_api_key=None,
        log_dir=Path("/tmp/data/logs"),
        log_level="INFO",
        log_max_bytes=10 * 1024 * 1024,
        log_backup_count=5,
    )

    monkeypatch.setattr("backend.app.main.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.main.get_dispatcher", lambda: FakeDispatcher())
    monkeypatch.setattr("backend.app.main.SchedulerService", FakeScheduler)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    assert FakeScheduler.started is True
    assert FakeScheduler.stopped is True


def test_configure_application_logging_creates_file(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=tmp_path,
        vault_dir=tmp_path / "vault",
        db_path=tmp_path / "state.db",
        default_timezone="Europe/Bucharest",
        youtube_mode="oauth",
        scheduler_enabled=False,
        scheduler_poll_interval_seconds=30,
        youtube_transcript_scheduler_poll_interval_seconds=20,
        youtube_daily_quota_limit=10000,
        youtube_quota_warning_percent=0.8,
        youtube_likes_cache_ttl_seconds=600,
        youtube_likes_recent_guard_seconds=45,
        youtube_likes_cache_max_items=500,
        youtube_background_sync_enabled=True,
        youtube_background_min_interval_seconds=120,
        youtube_background_hot_pages=2,
        youtube_background_backfill_pages_per_run=1,
        youtube_background_page_size=50,
        youtube_background_target_items=1000,
        youtube_transcript_cache_ttl_seconds=86400,
        youtube_transcript_background_sync_enabled=True,
        youtube_transcript_background_min_interval_seconds=20,
        youtube_transcript_background_recent_limit=1000,
        youtube_transcript_background_backoff_base_seconds=300,
        youtube_transcript_background_backoff_max_seconds=86400,
        youtube_transcript_background_ip_block_pause_seconds=3600,
        youtube_token_path=tmp_path / "youtube-token.json",
        youtube_client_secret_path=tmp_path / "youtube-client-secret.json",
        supadata_api_key=None,
        supadata_base_url="https://api.supadata.ai/v1",
        supadata_transcript_mode="native",
        supadata_http_timeout_seconds=30.0,
        supadata_poll_interval_seconds=1.0,
        supadata_poll_max_attempts=30,
        bucket_enrichment_enabled=False,
        bucket_enrichment_http_timeout_seconds=2.0,
        bucket_omdb_api_key=None,
        log_dir=tmp_path / "logs",
        log_level="INFO",
        log_max_bytes=1024 * 1024,
        log_backup_count=2,
    )
    log_file = configure_application_logging(settings)
    logger = logging.getLogger("active_workbench.test")
    logger.info("runtime-log-test")
    structlog.get_logger("active_workbench.telemetry").info(
        "telemetry",
        telemetry_event="test.event",
    )

    app_logger = logging.getLogger("active_workbench")
    assert len(app_logger.handlers) == 2
    levels = {handler.level for handler in app_logger.handlers}
    assert logging.INFO in levels
    assert logging.DEBUG in levels
    file_handlers = [
        handler for handler in app_logger.handlers if isinstance(handler, logging.FileHandler)
    ]
    assert len(file_handlers) == 1
    assert not isinstance(file_handlers[0], RotatingFileHandler)

    for handler in app_logger.handlers:
        handler.flush()
    telemetry_logger = logging.getLogger("active_workbench.telemetry")
    assert telemetry_logger.propagate is False
    assert len(telemetry_logger.handlers) == 1
    telemetry_handlers = [
        handler for handler in telemetry_logger.handlers if isinstance(handler, logging.FileHandler)
    ]
    assert len(telemetry_handlers) == 1
    for handler in telemetry_logger.handlers:
        handler.flush()

    assert log_file.exists()
    log_lines = [
        line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert log_lines

    parsed_events = [json.loads(line) for line in log_lines]
    runtime_event = next(
        event for event in parsed_events if event.get("event") == "runtime-log-test"
    )
    assert runtime_event["logger"] == "active_workbench.test"
    assert runtime_event["level"] == "info"
    assert runtime_event["pathname"]
    assert runtime_event["lineno"]
    assert all(event.get("telemetry_event") != "test.event" for event in parsed_events)

    telemetry_log_file = settings.log_dir / TELEMETRY_LOG_FILE_NAME
    assert telemetry_log_file.exists()
    telemetry_lines = [
        line for line in telemetry_log_file.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    telemetry_events = [json.loads(line) for line in telemetry_lines]
    telemetry_event = next(
        event for event in telemetry_events if event.get("telemetry_event") == "test.event"
    )
    assert telemetry_event["logger"] == "active_workbench.telemetry"


def test_stream_supports_color_detects_tty() -> None:
    class _TTY:
        def isatty(self) -> bool:
            return True

    class _Pipe:
        def isatty(self) -> bool:
            return False

    class _Broken:
        def isatty(self) -> bool:
            raise RuntimeError("boom")

    assert _stream_supports_color(_TTY()) is True
    assert _stream_supports_color(_Pipe()) is False
    assert _stream_supports_color(_Broken()) is False
    assert _stream_supports_color(object()) is False
