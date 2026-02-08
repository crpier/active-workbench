from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import AppSettings, load_settings
from backend.app.main import create_app
from backend.app.repositories.database import Database
from backend.app.repositories.memory_repository import MemoryRepository


def test_config_env_bool_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "1")
    enabled = load_settings()
    assert enabled.scheduler_enabled is True

    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "off")
    disabled = load_settings()
    assert disabled.scheduler_enabled is False

    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "invalid")
    fallback = load_settings()
    assert fallback.scheduler_enabled is True


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
        def run_due_jobs(self) -> None:
            return None

    class FakeScheduler:
        started = False
        stopped = False

        def __init__(self, dispatcher: FakeDispatcher, poll_interval_seconds: int) -> None:
            _ = dispatcher
            _ = poll_interval_seconds

        def start(self) -> None:
            FakeScheduler.started = True

        def stop(self) -> None:
            FakeScheduler.stopped = True

    settings = AppSettings(
        data_dir=Path("/tmp/data"),
        vault_dir=Path("/tmp/data/vault"),
        db_path=Path("/tmp/data/state.db"),
        default_timezone="Europe/Bucharest",
        youtube_mode="fixture",
        scheduler_enabled=True,
        scheduler_poll_interval_seconds=1,
        youtube_daily_quota_limit=10000,
        youtube_quota_warning_percent=0.8,
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
