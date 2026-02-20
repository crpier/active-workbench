from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

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
        probe_recent_on_miss: bool = False,
        recent_probe_pages: int = 1,
    ) -> object:
        _ = (limit, query, probe_recent_on_miss, recent_probe_pages)
        raise YouTubeRateLimitedError(
            "YouTube Data API is currently rate-limiting recent-likes refresh requests.",
            retry_after_seconds=600,
            scope="youtube_data_api_recent_probe",
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
            omdb_api_key=None,
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
