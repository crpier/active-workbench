from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.dependencies import reset_cached_dependencies
from backend.app.main import create_app
from backend.app.repositories.database import Database
from backend.app.repositories.youtube_cache_repository import (
    CachedLikeVideo,
    YouTubeCacheRepository,
)


@pytest.fixture(autouse=True)
def _wallabag_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setenv("ACTIVE_WORKBENCH_WALLABAG_ENABLED", "1")
    monkeypatch.setenv("ACTIVE_WORKBENCH_WALLABAG_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ACTIVE_WORKBENCH_WALLABAG_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("ACTIVE_WORKBENCH_WALLABAG_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("ACTIVE_WORKBENCH_WALLABAG_USERNAME", "test-user")
    monkeypatch.setenv("ACTIVE_WORKBENCH_WALLABAG_PASSWORD", "test-password")


def _seed_cached_youtube_data(data_dir: Path) -> None:
    now = datetime.now(UTC)

    def _iso(hours_ago: int) -> str:
        return (now - timedelta(hours=hours_ago)).isoformat()

    db = Database(data_dir / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.upsert_likes(
        videos=[
            CachedLikeVideo(
                video_id="test_cooking_001",
                title="How To Cook Leek And Potato Soup",
                liked_at=_iso(1),
                video_published_at=_iso(2),
                description="Simple leek soup tutorial with potato and stock.",
                channel_title="Test Cooking",
                tags=("soup", "leek", "recipe"),
            ),
            CachedLikeVideo(
                video_id="test_micro_001",
                title="Microservices Done Right - Real Lessons",
                liked_at=_iso(3),
                video_published_at=_iso(4),
                description="Architecture trade-offs and distributed systems pitfalls.",
                channel_title="Test Engineering",
                tags=("microservices", "architecture"),
            ),
            CachedLikeVideo(
                video_id="test_general_001",
                title="Weekly Productivity Systems",
                liked_at=_iso(5),
                video_published_at=_iso(6),
                description="A review of GPT-5.3 pros and cons for coding productivity.",
                channel_title="Test AI",
                tags=("gpt-5.3", "llm", "productivity"),
            ),
        ],
        max_items=500,
    )
    cache_repo.upsert_transcript(
        video_id="test_cooking_001",
        title="How To Cook Leek And Potato Soup",
        transcript=(
            "Today we're cooking a leek and potato soup. Chop the leeks and potatoes and simmer."
        ),
        source="supadata_captions",
        segments=[],
    )
    cache_repo.upsert_transcript(
        video_id="test_micro_001",
        title="Microservices Done Right - Real Lessons",
        transcript=(
            "Microservices help teams deploy independently, but they increase "
            "operational complexity."
        ),
        source="supadata_captions",
        segments=[],
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    data_dir = tmp_path / "runtime-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "youtube-token.json").write_text("{}", encoding="utf-8")
    (data_dir / "youtube-client-secret.json").write_text("{}", encoding="utf-8")
    _seed_cached_youtube_data(data_dir)

    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "oauth")
    monkeypatch.setenv("ACTIVE_WORKBENCH_SUPADATA_API_KEY", "test-supadata-key")
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY", "test-tmdb-key")
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_ENRICHMENT_ENABLED", "0")
    reset_cached_dependencies()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    reset_cached_dependencies()
