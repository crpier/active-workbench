from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.app.repositories.bucket_musicbrainz_quota_repository import (
    BucketMusicbrainzQuotaRepository,
)
from backend.app.repositories.database import Database
from backend.app.services.bucket_metadata_service import BucketMetadataService


def test_bucket_musicbrainz_quota_repository_blocks_after_soft_limit(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    repository = BucketMusicbrainzQuotaRepository(database)

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


def test_bucket_musicbrainz_quota_repository_blocks_burst_calls(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    repository = BucketMusicbrainzQuotaRepository(database)

    first = repository.try_consume_call(daily_soft_limit=10, min_interval_seconds=1.1)
    second = repository.try_consume_call(daily_soft_limit=10, min_interval_seconds=1.1)

    assert first.allowed is True
    assert second.allowed is False
    assert second.daily_limited is False
    assert second.burst_limited is True
    assert second.retry_after_seconds is not None
    assert second.retry_after_seconds > 0


def test_bucket_metadata_service_stops_musicbrainz_calls_after_soft_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    quota_repository = BucketMusicbrainzQuotaRepository(database)
    musicbrainz_urls: list[str] = []

    def _fake_fetch_json(
        url: str,
        *,
        timeout_seconds: float,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        _ = timeout_seconds
        assert headers is not None
        assert "User-Agent" in headers
        musicbrainz_urls.append(url)
        return {
            "release-groups": [
                {
                    "id": "5f408e6b-583f-3214-b71c-9f88ec829cdd",
                    "title": "Discovery",
                    "primary-type": "Album",
                    "first-release-date": "2001-03-07",
                    "score": "100",
                    "artist-credit": [{"name": "Daft Punk"}],
                }
            ]
        }

    monkeypatch.setattr(
        "backend.app.services.bucket_metadata_service._fetch_json",
        _fake_fetch_json,
    )

    service = BucketMetadataService(
        enrichment_enabled=True,
        http_timeout_seconds=0.5,
        tmdb_api_key="test-key",
        musicbrainz_quota_repository=quota_repository,
        musicbrainz_daily_soft_limit=1,
        musicbrainz_min_interval_seconds=0,
    )

    first = service.enrich(title="Discovery", domain="music", year=2001)
    second = service.enrich(title="Homework", domain="music", year=1997)

    assert first.provider == "musicbrainz"
    assert second.provider is None
    assert len(musicbrainz_urls) == 1
