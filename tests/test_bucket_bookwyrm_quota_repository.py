from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.app.repositories.bucket_bookwyrm_quota_repository import (
    BucketBookwyrmQuotaRepository,
)
from backend.app.repositories.database import Database
from backend.app.services.bucket_metadata_service import BucketMetadataService


def test_bucket_bookwyrm_quota_repository_blocks_after_soft_limit(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    repository = BucketBookwyrmQuotaRepository(database)

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


def test_bucket_bookwyrm_quota_repository_blocks_burst_calls(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    repository = BucketBookwyrmQuotaRepository(database)

    first = repository.try_consume_call(daily_soft_limit=10, min_interval_seconds=1.1)
    second = repository.try_consume_call(daily_soft_limit=10, min_interval_seconds=1.1)

    assert first.allowed is True
    assert second.allowed is False
    assert second.daily_limited is False
    assert second.burst_limited is True
    assert second.retry_after_seconds is not None
    assert second.retry_after_seconds > 0


def test_bucket_metadata_service_stops_bookwyrm_calls_after_soft_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    quota_repository = BucketBookwyrmQuotaRepository(database)
    bookwyrm_urls: list[str] = []

    def _fake_fetch_json_list(
        url: str,
        *,
        timeout_seconds: float,
        headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]] | None:
        _ = timeout_seconds
        assert headers is not None
        bookwyrm_urls.append(url)
        return [
            {
                "title": "Dune Messiah",
                "key": "https://bookwyrm.social/book/999",
                "author": "Frank Herbert",
                "year": 1969,
                "confidence": 0.8,
            }
        ]

    monkeypatch.setattr(
        "backend.app.services.bucket_metadata_service._fetch_json_list",
        _fake_fetch_json_list,
    )

    service = BucketMetadataService(
        enrichment_enabled=True,
        http_timeout_seconds=0.5,
        tmdb_api_key="test-key",
        bookwyrm_quota_repository=quota_repository,
        bookwyrm_daily_soft_limit=1,
        bookwyrm_min_interval_seconds=0,
    )

    first = service.enrich(title="Dune Messiah", domain="book", year=1969)
    second = service.enrich(title="Children of Dune", domain="book", year=1976)

    assert first.provider == "bookwyrm"
    assert second.provider is None
    assert len(bookwyrm_urls) == 1
