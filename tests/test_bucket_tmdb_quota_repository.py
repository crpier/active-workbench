from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.app.repositories.bucket_tmdb_quota_repository import BucketTmdbQuotaRepository
from backend.app.repositories.database import Database
from backend.app.services.bucket_metadata_service import BucketMetadataService


def test_bucket_tmdb_quota_repository_blocks_after_soft_limit(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    repository = BucketTmdbQuotaRepository(database)

    first = repository.try_consume_call(daily_soft_limit=3, min_interval_seconds=0)
    second = repository.try_consume_call(daily_soft_limit=3, min_interval_seconds=0)
    third = repository.try_consume_call(daily_soft_limit=3, min_interval_seconds=0)
    fourth = repository.try_consume_call(daily_soft_limit=3, min_interval_seconds=0)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is True
    assert fourth.allowed is False
    assert fourth.daily_limited is True
    assert fourth.burst_limited is False
    assert fourth.calls_today == 3


def test_bucket_tmdb_quota_repository_blocks_burst_calls(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    repository = BucketTmdbQuotaRepository(database)

    first = repository.try_consume_call(daily_soft_limit=10, min_interval_seconds=1.1)
    second = repository.try_consume_call(daily_soft_limit=10, min_interval_seconds=1.1)

    assert first.allowed is True
    assert second.allowed is False
    assert second.daily_limited is False
    assert second.burst_limited is True
    assert second.retry_after_seconds is not None
    assert second.retry_after_seconds > 0


def test_bucket_metadata_service_stops_tmdb_calls_after_soft_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    quota_repository = BucketTmdbQuotaRepository(database)
    tmdb_urls: list[str] = []

    def _fake_fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any] | None:
        _ = timeout_seconds
        if "/search/movie?" in url:
            tmdb_urls.append(url)
            return {
                "results": [
                    {
                        "id": 123,
                        "title": "First Movie",
                        "release_date": "2020-01-10",
                    }
                ]
            }
        if "/movie/123?" in url:
            return {
                "id": 123,
                "title": "First Movie",
                "release_date": "2020-01-10",
                "runtime": 100,
                "vote_average": 7.0,
                "popularity": 99.0,
                "genres": [{"id": 28, "name": "Action"}],
                "overview": "Test overview",
                "original_title": "First Movie",
                "original_language": "en",
                "production_countries": [{"iso_3166_1": "US"}],
                "imdb_id": "tt1234567",
            }
        return {"results": []}

    monkeypatch.setattr(
        "backend.app.services.bucket_metadata_service._fetch_json",
        _fake_fetch_json,
    )

    service = BucketMetadataService(
        enrichment_enabled=True,
        http_timeout_seconds=0.5,
        tmdb_api_key="test-key",
        tmdb_quota_repository=quota_repository,
        tmdb_daily_soft_limit=1,
        tmdb_min_interval_seconds=0,
    )

    first = service.enrich(title="First Movie", domain="movie", year=None)
    second = service.enrich(title="Second Movie", domain="movie", year=None)

    assert first.provider == "tmdb"
    assert second.provider is None
    assert len(tmdb_urls) == 1
