from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from backend.app.models.tool_contracts import ToolRequest
from backend.app.repositories.audit_repository import AuditRepository
from backend.app.repositories.bucket_repository import BucketRepository
from backend.app.repositories.database import Database
from backend.app.repositories.idempotency_repository import IdempotencyRepository
from backend.app.repositories.jobs_repository import JobsRepository
from backend.app.repositories.memory_repository import MemoryRepository
from backend.app.repositories.vault_repository import VaultRepository
from backend.app.repositories.youtube_quota_repository import YouTubeQuotaRepository
from backend.app.services.bucket_metadata_service import BucketMetadataService
from backend.app.services.tool_dispatcher import ToolDispatcher
from backend.app.services.youtube_service import YouTubeRateLimitedError


class _RateLimitedYouTubeService:
    @property
    def is_oauth_mode(self) -> bool:
        return True

    def list_recent_cached_only_with_metadata(
        self,
        limit: int,
        query: str | None = None,
        *,
        cursor: int = 0,
        probe_recent_on_miss: bool = False,
        recent_probe_pages: int = 1,
    ) -> object:
        _ = (limit, query, cursor, probe_recent_on_miss, recent_probe_pages)
        raise YouTubeRateLimitedError(
            "YouTube Data API is currently rate-limiting recent-likes refresh requests.",
            retry_after_seconds=600,
            scope="youtube_data_api_recent_probe",
        )


def _build_dispatcher(tmp_path: Path, *, metadata_service: BucketMetadataService) -> ToolDispatcher:
    database = Database(tmp_path / "state.db")
    database.initialize()
    return ToolDispatcher(
        audit_repository=AuditRepository(database),
        idempotency_repository=IdempotencyRepository(database),
        memory_repository=MemoryRepository(database),
        jobs_repository=JobsRepository(database),
        vault_repository=VaultRepository(tmp_path / "vault"),
        bucket_repository=BucketRepository(database),
        bucket_metadata_service=metadata_service,
        youtube_quota_repository=YouTubeQuotaRepository(database),
        youtube_service=cast(Any, _RateLimitedYouTubeService()),
        default_timezone="Europe/Bucharest",
        youtube_daily_quota_limit=10_000,
        youtube_quota_warning_percent=0.8,
    )


def test_youtube_likes_rate_limit_error_is_explicit_and_retryable(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    dispatcher = ToolDispatcher(
        audit_repository=AuditRepository(database),
        idempotency_repository=IdempotencyRepository(database),
        memory_repository=MemoryRepository(database),
        jobs_repository=JobsRepository(database),
        vault_repository=VaultRepository(tmp_path / "vault"),
        bucket_repository=BucketRepository(database),
        bucket_metadata_service=BucketMetadataService(
            enrichment_enabled=False,
            http_timeout_seconds=0.5,
            tmdb_api_key=None,
        ),
        youtube_quota_repository=YouTubeQuotaRepository(database),
        youtube_service=cast(Any, _RateLimitedYouTubeService()),
        default_timezone="Europe/Bucharest",
        youtube_daily_quota_limit=10_000,
        youtube_quota_warning_percent=0.8,
    )
    request = ToolRequest(
        tool="youtube.likes.list_recent",
        request_id=uuid4(),
        payload={
            "query": "recent controllers",
            "cache_miss_policy": "probe_recent",
            "recent_probe_pages": 2,
        },
    )

    response = dispatcher.execute("youtube.likes.list_recent", request)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "youtube_rate_limited"
    assert response.error.retryable is True
    assert response.result["status"] == "failed"
    assert "rate_limit" in response.result
    rate_limit = response.result["rate_limit"]
    assert rate_limit["scope"] == "youtube_data_api_recent_probe"
    assert rate_limit["retry_after_seconds"] == 600
    assert rate_limit["action"] == "wait_and_retry"
    assert "retry_after_utc" in rate_limit


def test_bucket_annotation_poll_marks_pending_attempts(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.db")
    database.initialize()
    dispatcher = ToolDispatcher(
        audit_repository=AuditRepository(database),
        idempotency_repository=IdempotencyRepository(database),
        memory_repository=MemoryRepository(database),
        jobs_repository=JobsRepository(database),
        vault_repository=VaultRepository(tmp_path / "vault"),
        bucket_repository=BucketRepository(database),
        bucket_metadata_service=BucketMetadataService(
            enrichment_enabled=False,
            http_timeout_seconds=0.5,
            tmdb_api_key=None,
        ),
        youtube_quota_repository=YouTubeQuotaRepository(database),
        youtube_service=cast(Any, _RateLimitedYouTubeService()),
        default_timezone="Europe/Bucharest",
        youtube_daily_quota_limit=10_000,
        youtube_quota_warning_percent=0.8,
    )

    add_request = ToolRequest(
        tool="bucket.item.add",
        request_id=uuid4(),
        payload={"title": "Unknown Title", "domain": "movie", "auto_enrich": False},
    )
    add_response = dispatcher.execute("bucket.item.add", add_request)
    assert add_response.ok is True

    poll_result = dispatcher.run_bucket_annotation_poll(limit=10)
    assert poll_result["attempted"] >= 1
    assert poll_result["pending"] >= 1

    search_request = ToolRequest(
        tool="bucket.item.search",
        request_id=uuid4(),
        payload={"query": "Unknown Title", "domain": "movie"},
    )
    search_response = dispatcher.execute("bucket.item.search", search_request)
    assert search_response.ok is True
    assert search_response.result["count"] == 1
    item = search_response.result["items"][0]
    assert item["annotated"] is False
    assert item["annotation_last_attempt_at"] is not None


def test_bucket_item_add_returns_clarification_for_ambiguous_tmdb_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any] | None:
        _ = timeout_seconds
        if "/search/movie?" in url:
            return {
                "results": [
                    {"id": 11, "title": "Dune", "release_date": "1984-12-14", "popularity": 80.0},
                    {"id": 22, "title": "Dune", "release_date": "2021-10-22", "popularity": 95.0},
                ]
            }
        return None

    monkeypatch.setattr(
        "backend.app.services.bucket_metadata_service._fetch_json",
        _fake_fetch_json,
    )
    dispatcher = _build_dispatcher(
        tmp_path,
        metadata_service=BucketMetadataService(
            enrichment_enabled=True,
            http_timeout_seconds=0.5,
            tmdb_api_key="test-key",
            tmdb_daily_soft_limit=50,
            tmdb_min_interval_seconds=0,
        ),
    )

    add_response = dispatcher.execute(
        "bucket.item.add",
        ToolRequest(
            tool="bucket.item.add",
            request_id=uuid4(),
            payload={"title": "Dune", "domain": "movie"},
        ),
    )

    assert add_response.ok is True
    assert add_response.result["status"] == "needs_clarification"
    assert add_response.result["write_performed"] is False
    assert add_response.result["resolution_status"] == "ambiguous"
    assert len(add_response.result["candidates"]) == 2

    search_response = dispatcher.execute(
        "bucket.item.search",
        ToolRequest(
            tool="bucket.item.search",
            request_id=uuid4(),
            payload={"query": "Dune", "domain": "movie"},
        ),
    )
    assert search_response.ok is True
    assert search_response.result["count"] == 0


def test_bucket_item_add_uses_tmdb_id_confirmation_to_write_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any] | None:
        _ = timeout_seconds
        if "/movie/22?" in url:
            return {
                "id": 22,
                "title": "Dune",
                "release_date": "2021-10-22",
                "runtime": 155,
                "vote_average": 8.1,
                "popularity": 120.0,
                "genres": [{"id": 878, "name": "Science Fiction"}],
                "overview": "A mythic hero's journey.",
                "original_title": "Dune",
                "original_language": "en",
                "production_countries": [{"iso_3166_1": "US"}],
                "imdb_id": "tt1160419",
            }
        return None

    monkeypatch.setattr(
        "backend.app.services.bucket_metadata_service._fetch_json",
        _fake_fetch_json,
    )
    dispatcher = _build_dispatcher(
        tmp_path,
        metadata_service=BucketMetadataService(
            enrichment_enabled=True,
            http_timeout_seconds=0.5,
            tmdb_api_key="test-key",
            tmdb_daily_soft_limit=50,
            tmdb_min_interval_seconds=0,
        ),
    )

    add_response = dispatcher.execute(
        "bucket.item.add",
        ToolRequest(
            tool="bucket.item.add",
            request_id=uuid4(),
            payload={"title": "Dune", "domain": "movie", "tmdb_id": 22},
        ),
    )

    assert add_response.ok is True
    assert add_response.result["status"] == "created"
    assert add_response.result["write_performed"] is True
    assert add_response.result["enriched"] is True
    assert add_response.result["enrichment_provider"] == "tmdb"
    assert add_response.result["resolution_status"] == "resolved"
    assert add_response.result["selected_candidate"]["tmdb_id"] == 22
    assert add_response.result["bucket_item"]["canonical_id"] == "tmdb:movie:22"


def test_bucket_item_add_allow_unresolved_writes_when_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any] | None:
        _ = timeout_seconds
        if "/search/movie?" in url:
            return {
                "results": [
                    {"id": 11, "title": "Dune", "release_date": "1984-12-14", "popularity": 80.0},
                    {"id": 22, "title": "Dune", "release_date": "2021-10-22", "popularity": 95.0},
                ]
            }
        return None

    monkeypatch.setattr(
        "backend.app.services.bucket_metadata_service._fetch_json",
        _fake_fetch_json,
    )
    dispatcher = _build_dispatcher(
        tmp_path,
        metadata_service=BucketMetadataService(
            enrichment_enabled=True,
            http_timeout_seconds=0.5,
            tmdb_api_key="test-key",
            tmdb_daily_soft_limit=50,
            tmdb_min_interval_seconds=0,
        ),
    )

    add_response = dispatcher.execute(
        "bucket.item.add",
        ToolRequest(
            tool="bucket.item.add",
            request_id=uuid4(),
            payload={"title": "Dune", "domain": "movie", "allow_unresolved": True},
        ),
    )

    assert add_response.ok is True
    assert add_response.result["status"] == "created"
    assert add_response.result["write_performed"] is True
    assert add_response.result["resolution_status"] == "ambiguous"
    assert add_response.result["enriched"] is False


def test_bucket_item_add_auto_resolves_high_confidence_tmdb_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any] | None:
        _ = timeout_seconds
        if "/search/movie?" in url:
            return {
                "results": [
                    {
                        "id": 603,
                        "title": "The Matrix",
                        "release_date": "1999-03-31",
                        "vote_average": 8.2,
                        "popularity": 110.0,
                        "overview": "A computer hacker learns reality is a simulation.",
                        "original_language": "en",
                    }
                ]
            }
        return None

    monkeypatch.setattr(
        "backend.app.services.bucket_metadata_service._fetch_json",
        _fake_fetch_json,
    )
    dispatcher = _build_dispatcher(
        tmp_path,
        metadata_service=BucketMetadataService(
            enrichment_enabled=True,
            http_timeout_seconds=0.5,
            tmdb_api_key="test-key",
            tmdb_daily_soft_limit=50,
            tmdb_min_interval_seconds=0,
        ),
    )

    add_response = dispatcher.execute(
        "bucket.item.add",
        ToolRequest(
            tool="bucket.item.add",
            request_id=uuid4(),
            payload={"title": "The Matrix", "domain": "movie"},
        ),
    )

    assert add_response.ok is True
    assert add_response.result["status"] == "created"
    assert add_response.result["write_performed"] is True
    assert add_response.result["resolution_status"] == "resolved"
    assert add_response.result["selected_candidate"]["tmdb_id"] == 603
    assert add_response.result["enriched"] is True
    assert add_response.result["enrichment_provider"] == "tmdb"


def test_bucket_item_complete_accepts_bucket_item_id_alias(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(
        tmp_path,
        metadata_service=BucketMetadataService(
            enrichment_enabled=False,
            http_timeout_seconds=0.5,
            tmdb_api_key=None,
        ),
    )

    add_response = dispatcher.execute(
        "bucket.item.add",
        ToolRequest(
            tool="bucket.item.add",
            request_id=uuid4(),
            payload={"title": "Oppenheimer", "domain": "movie", "auto_enrich": False},
        ),
    )
    assert add_response.ok is True
    item_id = add_response.result["bucket_item"]["item_id"]

    complete_response = dispatcher.execute(
        "bucket.item.complete",
        ToolRequest(
            tool="bucket.item.complete",
            request_id=uuid4(),
            payload={"bucket_item_id": item_id},
        ),
    )

    assert complete_response.ok is True
    assert complete_response.result["status"] == "completed"
    assert complete_response.result["bucket_item"]["status"] == "completed"


def test_bucket_item_add_skips_obscure_matches_for_common_titles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any] | None:
        _ = timeout_seconds
        if "/search/movie?" in url:
            return {
                "results": [
                    {
                        "id": 12106,
                        "title": "The Quick and the Dead",
                        "release_date": "1995-02-10",
                        "popularity": 43.0,
                        "vote_count": 1550,
                    },
                    {
                        "id": 26939,
                        "title": "The Quick and the Dead",
                        "release_date": "1987-06-01",
                        "popularity": 2.3,
                        "vote_count": 12,
                    },
                    {
                        "id": 328580,
                        "title": "The Quick and the Dead",
                        "release_date": "1963-01-01",
                        "popularity": 1.1,
                        "vote_count": 4,
                    },
                ]
            }
        return None

    monkeypatch.setattr(
        "backend.app.services.bucket_metadata_service._fetch_json",
        _fake_fetch_json,
    )
    dispatcher = _build_dispatcher(
        tmp_path,
        metadata_service=BucketMetadataService(
            enrichment_enabled=True,
            http_timeout_seconds=0.5,
            tmdb_api_key="test-key",
            tmdb_daily_soft_limit=50,
            tmdb_min_interval_seconds=0,
        ),
    )

    add_response = dispatcher.execute(
        "bucket.item.add",
        ToolRequest(
            tool="bucket.item.add",
            request_id=uuid4(),
            payload={"title": "The Quick and the Dead", "domain": "movie"},
        ),
    )

    assert add_response.ok is True
    assert add_response.result["status"] == "created"
    assert add_response.result["resolution_status"] == "resolved"
    assert add_response.result["selected_candidate"]["tmdb_id"] == 12106


def test_bucket_item_add_keeps_obscure_candidate_when_year_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any] | None:
        _ = timeout_seconds
        if "/search/movie?" in url:
            return {
                "results": [
                    {
                        "id": 12106,
                        "title": "The Quick and the Dead",
                        "release_date": "1995-02-10",
                        "popularity": 43.0,
                        "vote_count": 1550,
                    },
                    {
                        "id": 328580,
                        "title": "The Quick and the Dead",
                        "release_date": "1963-01-01",
                        "popularity": 1.1,
                        "vote_count": 4,
                    },
                ]
            }
        return None

    monkeypatch.setattr(
        "backend.app.services.bucket_metadata_service._fetch_json",
        _fake_fetch_json,
    )
    dispatcher = _build_dispatcher(
        tmp_path,
        metadata_service=BucketMetadataService(
            enrichment_enabled=True,
            http_timeout_seconds=0.5,
            tmdb_api_key="test-key",
            tmdb_daily_soft_limit=50,
            tmdb_min_interval_seconds=0,
        ),
    )

    add_response = dispatcher.execute(
        "bucket.item.add",
        ToolRequest(
            tool="bucket.item.add",
            request_id=uuid4(),
            payload={
                "title": "The Quick and the Dead",
                "domain": "movie",
                "year": 1963,
            },
        ),
    )

    assert add_response.ok is True
    assert add_response.result["status"] == "created"
    assert add_response.result["resolution_status"] == "resolved"
    assert add_response.result["selected_candidate"]["tmdb_id"] == 328580
