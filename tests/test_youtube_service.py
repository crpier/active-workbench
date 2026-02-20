from __future__ import annotations

import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from backend.app.repositories.database import Database
from backend.app.repositories.youtube_cache_repository import (
    CachedLikeVideo,
    YouTubeCacheRepository,
)
from backend.app.services.youtube_service import (
    SupadataTranscriptError,
    TranscriptProviderBlockedError,
    YouTubeRateLimitedError,
    YouTubeService,
    YouTubeServiceError,
    YouTubeTranscript,
    YouTubeTranscriptResult,
    YouTubeVideo,
    resolve_oauth_paths,
)


class _CaptureLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def _record(self, message: str, *args: object, **kwargs: object) -> None:
        _ = kwargs
        if args:
            try:
                rendered = message % args
            except Exception:
                rendered = f"{message} {' '.join(str(arg) for arg in args)}"
        else:
            rendered = message
        self.messages.append(rendered)

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        self._record(message, *args, **kwargs)

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        self._record(message, *args, **kwargs)


def _build_service_with_seeded_cache(tmp_path: Path) -> YouTubeService:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.upsert_likes(
        videos=[
            CachedLikeVideo(
                video_id="test_cooking_001",
                title="How To Cook Leek And Potato Soup",
                liked_at="2026-02-06T18:00:00+00:00",
                video_published_at="2026-02-06T18:00:00+00:00",
                description="Simple leek soup tutorial with potato and stock.",
                channel_title="Test Cooking",
                tags=("soup", "leek", "recipe"),
            ),
            CachedLikeVideo(
                video_id="test_micro_001",
                title="Microservices Done Right - Real Lessons",
                liked_at="2026-02-05T19:30:00+00:00",
                video_published_at="2026-02-05T19:30:00+00:00",
                description="Architecture trade-offs and distributed systems pitfalls.",
                channel_title="Test Engineering",
                tags=("microservices", "architecture"),
            ),
            CachedLikeVideo(
                video_id="test_general_001",
                title="Weekly Productivity Systems",
                liked_at="2026-02-04T15:00:00+00:00",
                video_published_at="2026-02-04T15:00:00+00:00",
                description="A review of GPT-5.3 pros and cons for coding productivity.",
                channel_title="Test AI",
                tags=("gpt-5.3", "llm", "productivity"),
            ),
        ],
        max_items=100,
    )
    cache_repo.upsert_transcript(
        video_id="test_cooking_001",
        title="How To Cook Leek And Potato Soup",
        transcript="Today we're cooking a leek and potato soup.",
        source="supadata_captions",
        segments=[],
    )
    return YouTubeService(mode="oauth", data_dir=tmp_path, cache_repository=cache_repo)


def test_cached_likes_and_transcript(tmp_path: Path) -> None:
    service = _build_service_with_seeded_cache(tmp_path)
    videos = service.list_recent_cached_only_with_metadata(limit=2, query="cook").videos
    assert videos
    transcript = service.get_transcript("test_cooking_001")
    assert transcript.transcript


def test_cached_query_natural_language_matches_keywords(tmp_path: Path) -> None:
    service = _build_service_with_seeded_cache(tmp_path)
    videos = service.list_recent_cached_only_with_metadata(
        limit=5,
        query="Somewhere I watched and liked a video about soup. Can you find it?",
    ).videos
    assert videos
    assert any("soup" in video.title.lower() for video in videos)


def test_cached_query_without_match_returns_empty(tmp_path: Path) -> None:
    service = _build_service_with_seeded_cache(tmp_path)
    videos = service.list_recent_cached_only_with_metadata(
        limit=5,
        query="quantum cryptography lecture",
    ).videos
    assert videos == []


def test_cached_query_matches_description_not_title(tmp_path: Path) -> None:
    service = _build_service_with_seeded_cache(tmp_path)
    videos = service.list_recent_cached_only_with_metadata(limit=5, query="gpt-5.3").videos
    assert videos
    assert videos[0].video_id == "test_general_001"

    phrase_videos = service.list_recent_cached_only_with_metadata(
        limit=5,
        query="I have recently watched a video about gpt-5.3. Can you find it?",
    ).videos
    assert phrase_videos
    assert phrase_videos[0].video_id == "test_general_001"


def test_oauth_mode_without_secrets_raises(tmp_path: Path) -> None:
    service = YouTubeService(mode="oauth", data_dir=tmp_path)

    with pytest.raises(YouTubeServiceError):
        service.list_recent(limit=1)


def test_oauth_mode_without_liked_videos_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "youtube-token.json").write_text("{}", encoding="utf-8")

    class FakeCredentials:
        valid = True
        expired = False
        refresh_token = None

        @classmethod
        def from_authorized_user_file(cls, _path: str, _scopes: list[str]) -> FakeCredentials:
            return cls()

    class FakeFlow:
        @classmethod
        def from_client_secrets_file(cls, _path: str, _scopes: list[str]) -> FakeFlow:
            return cls()

        def run_local_server(self, port: int = 0) -> FakeCredentials:
            _ = port
            return FakeCredentials()

    class FakeClient:
        def channels(self) -> FakeClient:
            return self

        def playlistItems(self) -> FakeClient:  # noqa: N802
            return self

        def videos(self) -> FakeClient:
            return self

        def list(self, **kwargs: object) -> FakeClient:
            self._kwargs = kwargs
            return self

        def execute(self) -> dict[str, object]:
            _kwargs = getattr(self, "_kwargs", {})
            if _kwargs.get("mine") is True and _kwargs.get("part") == "contentDetails":
                return {"items": [{"contentDetails": {"relatedPlaylists": {"likes": "LL"}}}]}
            if _kwargs.get("playlistId") == "LL":
                return {"items": []}
            return {"items": []}

    def fake_import_module(name: str) -> object:
        def _build(*_args: object, **_kwargs: object) -> FakeClient:
            return FakeClient()

        if name == "google.auth.transport.requests":
            return types.SimpleNamespace(Request=object)
        if name == "google.oauth2.credentials":
            return types.SimpleNamespace(Credentials=FakeCredentials)
        if name == "google_auth_oauthlib.flow":
            return types.SimpleNamespace(InstalledAppFlow=FakeFlow)
        if name == "googleapiclient.discovery":
            return types.SimpleNamespace(build=_build)
        raise AssertionError(f"Unexpected module import: {name}")

    monkeypatch.setattr("backend.app.services.youtube_service.import_module", fake_import_module)

    service = YouTubeService(mode="oauth", data_dir=tmp_path)
    with pytest.raises(YouTubeServiceError, match="No liked videos available"):
        service.list_recent(limit=5)


def test_oauth_refresh_invalid_grant_requires_reauth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "youtube-token.json").write_text("{}", encoding="utf-8")

    class FakeCredentials:
        valid = False
        expired = True
        refresh_token = "refresh-token"

        @classmethod
        def from_authorized_user_file(cls, _path: str, _scopes: list[str]) -> FakeCredentials:
            return cls()

        def refresh(self, _request: object) -> None:
            raise RuntimeError("invalid_grant: Token has been expired or revoked.")

    class FakeFlow:
        @classmethod
        def from_client_secrets_file(cls, _path: str, _scopes: list[str]) -> FakeFlow:
            return cls()

        def run_local_server(self, port: int = 0) -> FakeCredentials:
            _ = port
            return FakeCredentials()

    def fake_import_module(name: str) -> object:
        def _build(*_args: object, **_kwargs: object) -> object:
            return object()

        if name == "google.auth.transport.requests":
            return types.SimpleNamespace(Request=object)
        if name == "google.oauth2.credentials":
            return types.SimpleNamespace(Credentials=FakeCredentials)
        if name == "google_auth_oauthlib.flow":
            return types.SimpleNamespace(InstalledAppFlow=FakeFlow)
        if name == "googleapiclient.discovery":
            return types.SimpleNamespace(build=_build)
        raise AssertionError(f"Unexpected module import: {name}")

    monkeypatch.setattr("backend.app.services.youtube_service.import_module", fake_import_module)

    service = YouTubeService(mode="oauth", data_dir=tmp_path)
    with pytest.raises(YouTubeServiceError, match="run `just youtube-auth`"):
        service.list_recent(limit=1)


def test_resolve_oauth_paths_default(tmp_path: Path) -> None:
    token_path, secret_path = resolve_oauth_paths(tmp_path)
    assert token_path == (tmp_path / "youtube-token.json").resolve()
    assert secret_path == (tmp_path / "youtube-client-secret.json").resolve()


def test_resolve_oauth_paths_override(tmp_path: Path) -> None:
    token_override = tmp_path / "custom-token.json"
    secret_override = tmp_path / "custom-secret.json"

    token_path, secret_path = resolve_oauth_paths(
        tmp_path,
        token_override=token_override,
        secret_override=secret_override,
    )
    assert token_path == token_override.resolve()
    assert secret_path == secret_override.resolve()


def test_oauth_mode_with_mocked_modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "youtube-token.json").write_text("{}", encoding="utf-8")

    class FakeCredentials:
        valid = True
        expired = False
        refresh_token = None

        @classmethod
        def from_authorized_user_file(cls, _path: str, _scopes: list[str]) -> FakeCredentials:
            return cls()

        def refresh(self, _request: object) -> None:
            return None

        def to_json(self) -> str:
            return "{}"

    class FakeFlow:
        @classmethod
        def from_client_secrets_file(cls, _path: str, _scopes: list[str]) -> FakeFlow:
            return cls()

        def run_local_server(self, port: int = 0) -> FakeCredentials:
            return FakeCredentials()

    class FakeClient:
        def channels(self) -> FakeClient:
            return self

        def playlistItems(self) -> FakeClient:  # noqa: N802
            return self

        def videos(self) -> FakeClient:
            return self

        def list(self, **kwargs: object) -> FakeClient:
            self._kwargs = kwargs
            return self

        def execute(self) -> dict[str, object]:
            kwargs = getattr(self, "_kwargs", {})
            if kwargs.get("mine") is True and kwargs.get("part") == "contentDetails":
                return {"items": [{"contentDetails": {"relatedPlaylists": {"likes": "LL"}}}]}
            if kwargs.get("playlistId") == "LL":
                return {
                    "items": [
                        {
                            "snippet": {
                                "resourceId": {"videoId": "oauth_video_1"},
                                "title": "OAuth Cooking",
                                "publishedAt": "2026-02-01T12:00:00Z",
                            },
                            "contentDetails": {"videoPublishedAt": "2026-01-20T09:00:00Z"},
                        }
                    ]
                }
            if kwargs.get("id") == "oauth_video_1":
                return {
                    "items": [
                        {
                            "id": "oauth_video_1",
                            "snippet": {
                                "title": "OAuth Cooking",
                                "description": "GPT-5.3 analysis and fallback transcript",
                                "channelTitle": "OAuth Channel",
                                "tags": ["gpt-5.3", "ai"],
                            },
                        }
                    ]
                }
            return {"items": []}

    def fake_import_module(name: str) -> object:
        def _build(*_args: object, **_kwargs: object) -> FakeClient:
            return FakeClient()

        if name == "google.auth.transport.requests":
            return types.SimpleNamespace(Request=object)
        if name == "google.oauth2.credentials":
            return types.SimpleNamespace(Credentials=FakeCredentials)
        if name == "google_auth_oauthlib.flow":
            return types.SimpleNamespace(InstalledAppFlow=FakeFlow)
        if name == "googleapiclient.discovery":
            return types.SimpleNamespace(build=_build)
        raise AssertionError(f"Unexpected module import: {name}")

    monkeypatch.setattr("backend.app.services.youtube_service.import_module", fake_import_module)

    def _supadata_success(
        *,
        url: str,
        api_key: str,
        timeout_seconds: float,
        params: dict[str, str] | None,
    ) -> tuple[int, dict[str, Any]]:
        assert api_key == "supadata-test-key"
        assert timeout_seconds > 0
        assert params is not None
        assert params.get("url") == "https://www.youtube.com/watch?v=oauth_video_1"
        assert params.get("text") == "false"
        assert params.get("lang") == "ro"
        assert url.endswith("/transcript")
        return (
            200,
            {
                "content": [
                    {"text": "first line", "offset": 0, "duration": 1.0},
                    {"text": "second line", "offset": 1.0, "duration": 0.8},
                ]
            },
        )

    monkeypatch.setattr(
        "backend.app.services.youtube_service._fetch_supadata_json", _supadata_success
    )

    service = YouTubeService(mode="oauth", data_dir=tmp_path, supadata_api_key="supadata-test-key")
    videos = service.list_recent(limit=1)
    assert videos and videos[0].video_id == "oauth_video_1"
    assert videos[0].liked_at == "2026-02-01T12:00:00Z"

    filtered = service.list_recent(limit=5, query="gpt-5.3")
    assert filtered and filtered[0].video_id == "oauth_video_1"

    transcript = service.get_transcript("oauth_video_1")
    assert "first line" in transcript.transcript
    assert transcript.source == "supadata_captions"


def test_oauth_likes_cache_hit_returns_zero_units(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.replace_likes(
        videos=[
            CachedLikeVideo(
                video_id="cached_1",
                title="Cached Video",
                liked_at="2026-02-08T12:00:00+00:00",
                video_published_at="2026-02-07T12:00:00+00:00",
                description="cached description",
                channel_title="Cached Channel",
                tags=("cached",),
            )
        ],
        max_items=100,
    )

    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
        likes_cache_ttl_seconds=600,
        likes_recent_guard_seconds=45,
        likes_cache_max_items=100,
    )
    result = service.list_recent_with_metadata(limit=1, query="cached")

    assert result.cache_hit is True
    assert result.estimated_api_units == 0
    assert result.videos and result.videos[0].video_id == "cached_1"


def test_oauth_likes_cache_only_does_not_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.replace_likes(
        videos=[
            CachedLikeVideo(
                video_id="cached_only_1",
                title="Cached Only Video",
                liked_at="2026-02-08T12:00:00+00:00",
            )
        ],
        max_items=100,
    )

    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
    )

    def _unexpected_refresh(*, limit: int, enrich_metadata: bool) -> None:
        _ = limit
        _ = enrich_metadata
        raise AssertionError("refresh should not be called for cache-only path")

    monkeypatch.setattr(service, "_refresh_likes_cache", _unexpected_refresh)

    result = service.list_recent_cached_only_with_metadata(limit=1, query="cached")
    assert result.videos and result.videos[0].video_id == "cached_only_1"
    assert result.estimated_api_units == 0


def test_oauth_likes_cache_only_probe_recent_on_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.replace_likes(
        videos=[
            CachedLikeVideo(
                video_id="cached_only_1",
                title="Cached Only Video",
                liked_at="2026-02-08T12:00:00+00:00",
                description="unrelated topic",
            )
        ],
        max_items=100,
    )

    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
    )

    def _fake_probe(*, recent_probe_pages: int, enrich_metadata: bool) -> tuple[int, int]:
        _ = enrich_metadata
        assert recent_probe_pages == 2
        cache_repo.upsert_likes(
            videos=[
                CachedLikeVideo(
                    video_id="probed_1",
                    title="Probed Soup Video",
                    liked_at="2026-02-08T12:01:00+00:00",
                    description="potato soup",
                )
            ],
            max_items=100,
        )
        return 4, 1

    monkeypatch.setattr(service, "_probe_recent_likes_cache", _fake_probe)

    result = service.list_recent_cached_only_with_metadata(
        limit=1,
        query="soup",
        probe_recent_on_miss=True,
        recent_probe_pages=2,
    )
    assert result.videos and result.videos[0].video_id == "probed_1"
    assert result.estimated_api_units == 4
    assert result.cache_miss is False
    assert result.recent_probe_applied is True
    assert result.recent_probe_pages_used == 1


def test_oauth_search_recent_content_matches_transcript(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.upsert_likes(
        videos=[
            CachedLikeVideo(
                video_id="match_1",
                title="Console teardown",
                liked_at="2026-02-15T12:00:00+00:00",
                description="hardware video",
            ),
            CachedLikeVideo(
                video_id="other_1",
                title="Gardening tips",
                liked_at="2026-02-15T11:00:00+00:00",
                description="plants",
            ),
        ],
        max_items=100,
    )
    cache_repo.upsert_transcript(
        video_id="match_1",
        title="Console teardown",
        transcript="We tested game controllers and button latency.",
        source="youtube_captions",
        segments=[],
    )

    service = YouTubeService(mode="oauth", data_dir=tmp_path, cache_repository=cache_repo)
    result = service.search_recent_content_with_metadata(
        query="game controllers",
        window_days=7,
        limit=5,
        probe_recent_on_miss=False,
        recent_probe_pages=1,
    )

    assert result.matches
    assert result.matches[0].video.video_id == "match_1"
    assert "transcript" in result.matches[0].matched_in
    assert result.recent_videos_count == 2
    assert result.transcripts_available_count == 1


def test_oauth_search_recent_content_without_window_searches_full_cache(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.upsert_likes(
        videos=[
            CachedLikeVideo(
                video_id="old_kimi",
                title="Kimi K2.5 deep dive",
                liked_at="2025-07-01T10:00:00+00:00",
                description="older but still relevant",
            ),
        ],
        max_items=100,
    )
    cache_repo.upsert_transcript(
        video_id="old_kimi",
        title="Kimi K2.5 deep dive",
        transcript="Great notes about Kimi K2.5",
        source="supadata_captions",
        segments=[],
    )

    service = YouTubeService(mode="oauth", data_dir=tmp_path, cache_repository=cache_repo)

    all_time_result = service.search_recent_content_with_metadata(
        query="Kimi K2.5",
        window_days=None,
        limit=5,
        probe_recent_on_miss=False,
        recent_probe_pages=1,
    )
    assert all_time_result.matches
    assert all_time_result.matches[0].video.video_id == "old_kimi"

    limited_result = service.search_recent_content_with_metadata(
        query="Kimi K2.5",
        window_days=7,
        limit=5,
        probe_recent_on_miss=False,
        recent_probe_pages=1,
    )
    assert limited_result.matches == []


def test_oauth_likes_recent_query_refreshes_when_cache_is_fresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    @dataclass(frozen=True)
    class _FakeOAuthFetch:
        videos: list[YouTubeVideo]
        estimated_api_units: int

    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.replace_likes(
        videos=[
            CachedLikeVideo(
                video_id="old_1",
                title="Old Video",
                liked_at="2026-02-08T11:00:00+00:00",
                video_published_at="2026-02-07T10:00:00+00:00",
                description="old",
                channel_title="Old",
                tags=(),
            )
        ],
        max_items=100,
    )

    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
        likes_cache_ttl_seconds=600,
        likes_recent_guard_seconds=120,
        likes_cache_max_items=100,
    )

    calls: list[tuple[int, bool]] = []

    def _fake_refresh(*, limit: int, enrich_metadata: bool) -> _FakeOAuthFetch:
        calls.append((limit, enrich_metadata))
        return _FakeOAuthFetch(
            videos=[
                YouTubeVideo(
                    video_id="new_1",
                    title="Monoliths Talk",
                    published_at="2026-02-08T12:05:00+00:00",
                    liked_at="2026-02-08T12:05:00+00:00",
                    video_published_at="2026-02-08T10:00:00+00:00",
                    description="modular monoliths",
                    channel_title="NDC",
                    tags=("monoliths",),
                )
            ],
            estimated_api_units=3,
        )

    monkeypatch.setattr(service, "_refresh_likes_cache", _fake_refresh)
    result = service.list_recent_with_metadata(
        limit=1,
        query="what's my most recent liked video about monoliths",
    )

    assert calls
    assert result.cache_hit is False
    assert result.refreshed is True
    assert result.estimated_api_units == 3
    assert result.videos and result.videos[0].video_id == "new_1"


def test_oauth_transcript_cache_hit_returns_zero_units(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.upsert_transcript(
        video_id="cached_video",
        title="Cached Transcript Video",
        transcript="cached transcript text",
        source="youtube_captions",
        segments=[{"text": "cached", "start": 0.0, "duration": 1.0}],
    )

    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
        transcript_cache_ttl_seconds=3600,
    )
    result = service.get_transcript_with_metadata("cached_video")

    assert result.cache_hit is True
    assert result.estimated_api_units == 0
    assert result.transcript.transcript == "cached transcript text"


def test_oauth_transcript_requires_supadata_key_when_cache_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("ACTIVE_WORKBENCH_SUPADATA_API_KEY", raising=False)
    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=None,
    )
    with pytest.raises(YouTubeServiceError, match="ACTIVE_WORKBENCH_SUPADATA_API_KEY"):
        service.get_transcript_with_metadata("video_without_cache")


def test_oauth_transcript_polls_supadata_job_until_complete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        supadata_api_key="supadata-test-key",
        supadata_poll_interval_seconds=0.01,
        supadata_poll_max_attempts=5,
    )

    def _fake_snippet(
        video_id: str,
        data_dir: Path,
        *,
        token_path: Path | None = None,
        secrets_path: Path | None = None,
    ) -> object:
        _ = video_id
        _ = data_dir
        _ = token_path
        _ = secrets_path
        return types.SimpleNamespace(title="Polled Title", description=None)

    monkeypatch.setattr("backend.app.services.youtube_service._fetch_video_snippet", _fake_snippet)

    calls: list[str] = []

    def _fake_supadata(
        *,
        url: str,
        api_key: str,
        timeout_seconds: float,
        params: dict[str, str] | None,
    ) -> tuple[int, dict[str, Any]]:
        _ = timeout_seconds
        assert api_key == "supadata-test-key"
        calls.append(url)
        if url.endswith("/transcript"):
            assert params is not None and params["mode"] == "native"
            assert params["lang"] == "ro"
            return 202, {"jobId": "job_123", "status": "queued"}
        if url.endswith("/transcript/job_123"):
            if len(calls) == 2:
                return 200, {"status": "processing"}
            return 200, {"status": "completed", "content": [{"text": "done", "offset": 0.0}]}
        raise AssertionError(f"Unexpected url: {url}")

    monkeypatch.setattr("backend.app.services.youtube_service._fetch_supadata_json", _fake_supadata)

    def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("backend.app.services.youtube_service.time.sleep", _fake_sleep)

    result = service.get_transcript_with_metadata("oauth_video_1")

    assert result.transcript.source == "supadata_captions"
    assert result.transcript.transcript == "done"
    assert result.transcript.segments == [{"text": "done", "start": 0.0}]


def test_oauth_transcript_unavailable_includes_supadata_request_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        supadata_api_key="supadata-test-key",
    )

    def _fake_snippet(
        video_id: str,
        data_dir: Path,
        *,
        token_path: Path | None = None,
        secrets_path: Path | None = None,
    ) -> object:
        _ = video_id
        _ = data_dir
        _ = token_path
        _ = secrets_path
        return types.SimpleNamespace(title="No Transcript", description=None)

    monkeypatch.setattr("backend.app.services.youtube_service._fetch_video_snippet", _fake_snippet)

    calls = 0

    def _fake_supadata(
        *,
        url: str,
        api_key: str,
        timeout_seconds: float,
        params: dict[str, str] | None,
    ) -> tuple[int, dict[str, Any]]:
        nonlocal calls
        calls += 1
        _ = url
        _ = api_key
        _ = timeout_seconds
        _ = params
        return 206, {
            "request_id": "supa_req_123",
            "error": "transcript-unavailable",
            "message": "Transcript Unavailable",
            "details": "No transcript is available for this video",
        }

    monkeypatch.setattr("backend.app.services.youtube_service._fetch_supadata_json", _fake_supadata)
    monkeypatch.setattr("backend.app.services.youtube_service.time.sleep", lambda _seconds: None)

    with pytest.raises(
        SupadataTranscriptError,
        match="supadata_request_id=supa_req_123",
    ):
        service.get_transcript_with_metadata("oauth_video_1")
    assert calls == 3


def test_oauth_transcript_unavailable_immediate_retries_can_recover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        supadata_api_key="supadata-test-key",
    )

    def _fake_snippet(
        video_id: str,
        data_dir: Path,
        *,
        token_path: Path | None = None,
        secrets_path: Path | None = None,
    ) -> object:
        _ = video_id
        _ = data_dir
        _ = token_path
        _ = secrets_path
        return types.SimpleNamespace(title="Retry Target", description=None)

    monkeypatch.setattr("backend.app.services.youtube_service._fetch_video_snippet", _fake_snippet)

    calls = 0

    def _fake_supadata(
        *,
        url: str,
        api_key: str,
        timeout_seconds: float,
        params: dict[str, str] | None,
    ) -> tuple[int, dict[str, Any]]:
        nonlocal calls
        _ = url
        _ = api_key
        _ = timeout_seconds
        _ = params
        calls += 1
        if calls < 3:
            return 206, {
                "request_id": f"supa_req_retry_{calls}",
                "error": "transcript-unavailable",
                "message": "Transcript Unavailable",
                "details": "No transcript is available for this video",
            }
        return 200, {
            "request_id": "supa_req_retry_3",
            "content": [{"text": "recovered transcript", "offset": 0.0}],
        }

    monkeypatch.setattr("backend.app.services.youtube_service._fetch_supadata_json", _fake_supadata)
    monkeypatch.setattr("backend.app.services.youtube_service.time.sleep", lambda _seconds: None)

    result = service.get_transcript_with_metadata("oauth_video_1")
    assert result.transcript.transcript == "recovered transcript"
    assert result.provider_request_id == "supa_req_retry_3"
    assert calls == 3


def test_oauth_background_sync_populates_likes_with_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "youtube-token.json").write_text("{}", encoding="utf-8")

    class FakeCredentials:
        valid = True
        expired = False
        refresh_token = None

        @classmethod
        def from_authorized_user_file(cls, _path: str, _scopes: list[str]) -> FakeCredentials:
            return cls()

    class FakeFlow:
        @classmethod
        def from_client_secrets_file(cls, _path: str, _scopes: list[str]) -> FakeFlow:
            return cls()

        def run_local_server(self, port: int = 0) -> FakeCredentials:
            _ = port
            return FakeCredentials()

    class FakeClient:
        def channels(self) -> FakeClient:
            return self

        def playlistItems(self) -> FakeClient:  # noqa: N802
            return self

        def videos(self) -> FakeClient:
            return self

        def list(self, **kwargs: object) -> FakeClient:
            self._kwargs = kwargs
            return self

        def execute(self) -> dict[str, object]:
            kwargs = getattr(self, "_kwargs", {})
            if kwargs.get("mine") is True and kwargs.get("part") == "contentDetails":
                return {"items": [{"contentDetails": {"relatedPlaylists": {"likes": "LL"}}}]}
            if kwargs.get("playlistId") == "LL":
                if kwargs.get("pageToken") == "p2":
                    return {
                        "items": [
                            {
                                "snippet": {
                                    "resourceId": {"videoId": "vid_2"},
                                    "title": "Second Video",
                                    "publishedAt": "2026-02-08T11:00:00Z",
                                },
                                "contentDetails": {"videoPublishedAt": "2026-01-31T10:00:00Z"},
                            }
                        ]
                    }
                return {
                    "items": [
                        {
                            "snippet": {
                                "resourceId": {"videoId": "vid_1"},
                                "title": "First Video",
                                "publishedAt": "2026-02-08T12:00:00Z",
                            },
                            "contentDetails": {"videoPublishedAt": "2026-02-01T10:00:00Z"},
                        }
                    ],
                    "nextPageToken": "p2",
                }
            if kwargs.get("id") == "vid_1":
                return {
                    "items": [
                        {
                            "id": "vid_1",
                            "snippet": {
                                "description": "desc 1",
                                "channelId": "ch_1",
                                "channelTitle": "Channel One",
                                "categoryId": "22",
                                "defaultLanguage": "en",
                                "defaultAudioLanguage": "en-US",
                                "liveBroadcastContent": "none",
                                "tags": ["tag1"],
                                "thumbnails": {"default": {"url": "https://example.com/1.jpg"}},
                            },
                            "contentDetails": {
                                "duration": "PT5M3S",
                                "caption": "true",
                                "definition": "hd",
                                "dimension": "2d",
                            },
                            "status": {
                                "privacyStatus": "public",
                                "licensedContent": True,
                                "madeForKids": False,
                            },
                            "statistics": {
                                "viewCount": "101",
                                "likeCount": "9",
                                "commentCount": "1",
                            },
                            "topicDetails": {
                                "topicCategories": ["https://en.wikipedia.org/wiki/Food"]
                            },
                        }
                    ]
                }
            if kwargs.get("id") == "vid_2":
                return {
                    "items": [
                        {
                            "id": "vid_2",
                            "snippet": {
                                "description": "desc 2",
                                "channelId": "ch_2",
                                "channelTitle": "Channel Two",
                                "liveBroadcastContent": "none",
                                "tags": ["tag2"],
                            },
                            "contentDetails": {"duration": "PT45S", "caption": "false"},
                            "status": {
                                "privacyStatus": "public",
                                "licensedContent": False,
                                "madeForKids": False,
                            },
                            "statistics": {
                                "viewCount": "50",
                                "likeCount": "4",
                                "commentCount": "0",
                            },
                            "topicDetails": {"topicCategories": []},
                        }
                    ]
                }
            return {"items": []}

    def fake_import_module(name: str) -> object:
        def _build(*_args: object, **_kwargs: object) -> FakeClient:
            return FakeClient()

        if name == "google.auth.transport.requests":
            return types.SimpleNamespace(Request=object)
        if name == "google.oauth2.credentials":
            return types.SimpleNamespace(Credentials=FakeCredentials)
        if name == "google_auth_oauthlib.flow":
            return types.SimpleNamespace(InstalledAppFlow=FakeFlow)
        if name == "googleapiclient.discovery":
            return types.SimpleNamespace(build=_build)
        raise AssertionError(f"Unexpected module import: {name}")

    monkeypatch.setattr("backend.app.services.youtube_service.import_module", fake_import_module)

    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
        likes_background_min_interval_seconds=0,
        likes_background_hot_pages=1,
        likes_background_backfill_pages_per_run=1,
        likes_background_page_size=1,
        likes_background_target_items=100,
    )

    service.run_background_likes_sync()

    rows = cache_repo.list_likes(limit=10)
    assert [row.video_id for row in rows] == ["vid_1", "vid_2"]
    assert rows[0].channel_id == "ch_1"
    assert rows[0].duration_seconds == 303
    assert rows[0].caption_available is True
    assert rows[0].statistics_view_count == 101
    assert rows[0].topic_categories == ("https://en.wikipedia.org/wiki/Food",)
    assert cache_repo.get_cache_state_value("likes_background_backfill_next_page_token") is None


def test_oauth_background_transcript_sync_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.upsert_likes(
        videos=[
            CachedLikeVideo(
                video_id="vid_t_1",
                title="Transcript Target",
                liked_at="2026-02-10T12:00:00+00:00",
            )
        ],
        max_items=100,
    )
    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
        transcript_background_min_interval_seconds=0,
    )

    def _fake_get_transcript(video_id: str) -> YouTubeTranscriptResult:
        cache_repo.upsert_transcript(
            video_id=video_id,
            title="Transcript Target",
            transcript="hello from background sync",
            source="youtube_captions",
            segments=[],
        )
        return YouTubeTranscriptResult(
            transcript=YouTubeTranscript(
                video_id=video_id,
                title="Transcript Target",
                transcript="hello from background sync",
                source="youtube_captions",
                segments=[],
            ),
            estimated_api_units=1,
            cache_hit=False,
        )

    monkeypatch.setattr(service, "get_transcript_with_metadata", _fake_get_transcript)
    captured_logger = _CaptureLogger()
    monkeypatch.setattr("backend.app.services.youtube_service.LOGGER", captured_logger)

    service.run_background_transcript_sync()

    cached = cache_repo.get_fresh_transcript(video_id="vid_t_1", ttl_seconds=3600)
    assert cached is not None
    assert cached.transcript == "hello from background sync"
    assert cache_repo.get_transcript_sync_attempts(video_id="vid_t_1") == 1
    assert any("youtube transcript background_sync start" in msg for msg in captured_logger.messages)
    assert any("provider=youtube" in msg for msg in captured_logger.messages)


def test_oauth_background_transcript_sync_start_log_includes_supadata_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.upsert_likes(
        videos=[
            CachedLikeVideo(
                video_id="vid_t_supadata",
                title="Transcript Target",
                liked_at="2026-02-10T12:00:00+00:00",
            )
        ],
        max_items=100,
    )
    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
        transcript_background_min_interval_seconds=0,
        supadata_api_key="supadata-test-key",
    )

    def _fake_get_transcript(video_id: str) -> YouTubeTranscriptResult:
        cache_repo.upsert_transcript(
            video_id=video_id,
            title="Transcript Target",
            transcript="hello from supadata provider run",
            source="supadata_captions",
            segments=[],
        )
        return YouTubeTranscriptResult(
            transcript=YouTubeTranscript(
                video_id=video_id,
                title="Transcript Target",
                transcript="hello from supadata provider run",
                source="supadata_captions",
                segments=[],
            ),
            estimated_api_units=1,
            cache_hit=False,
        )

    monkeypatch.setattr(service, "get_transcript_with_metadata", _fake_get_transcript)
    captured_logger = _CaptureLogger()
    monkeypatch.setattr("backend.app.services.youtube_service.LOGGER", captured_logger)

    service.run_background_transcript_sync()

    assert any("youtube transcript background_sync start" in msg for msg in captured_logger.messages)
    assert any("provider=supadata" in msg for msg in captured_logger.messages)


def test_oauth_background_transcript_sync_failure_backoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.upsert_likes(
        videos=[
            CachedLikeVideo(
                video_id="vid_t_fail",
                title="Transcript Failure Target",
                liked_at="2026-02-10T12:00:00+00:00",
            )
        ],
        max_items=100,
    )
    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
        transcript_background_min_interval_seconds=0,
        transcript_background_backoff_base_seconds=60,
        transcript_background_backoff_max_seconds=600,
    )

    def _failing_get_transcript(_video_id: str) -> YouTubeTranscriptResult:
        raise YouTubeServiceError("forced transcript failure")

    monkeypatch.setattr(service, "get_transcript_with_metadata", _failing_get_transcript)
    captured_logger = _CaptureLogger()
    monkeypatch.setattr("backend.app.services.youtube_service.LOGGER", captured_logger)

    service.run_background_transcript_sync()
    service.run_background_transcript_sync()

    assert cache_repo.get_transcript_sync_attempts(video_id="vid_t_fail") == 1
    assert any("youtube transcript background_sync failed" in msg for msg in captured_logger.messages)
    assert any("provider=youtube" in msg for msg in captured_logger.messages)
    assert any("error_type=YouTubeServiceError" in msg for msg in captured_logger.messages)
    assert any("error=forced transcript failure" in msg for msg in captured_logger.messages)


def test_oauth_background_transcript_sync_ip_block_global_pause(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    cache_repo.upsert_likes(
        videos=[
            CachedLikeVideo(
                video_id="vid_block_1",
                title="Blocked One",
                liked_at="2026-02-10T12:00:00+00:00",
            ),
            CachedLikeVideo(
                video_id="vid_block_2",
                title="Blocked Two",
                liked_at="2026-02-10T11:00:00+00:00",
            ),
        ],
        max_items=100,
    )
    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
        transcript_background_min_interval_seconds=0,
        transcript_background_backoff_base_seconds=60,
        transcript_background_backoff_max_seconds=600,
        transcript_background_ip_block_pause_seconds=600,
    )

    def _ip_blocked(_video_id: str) -> YouTubeTranscriptResult:
        raise TranscriptProviderBlockedError("IpBlocked")

    monkeypatch.setattr(service, "get_transcript_with_metadata", _ip_blocked)

    service.run_background_transcript_sync()
    service.run_background_transcript_sync()

    assert cache_repo.get_transcript_sync_attempts(video_id="vid_block_1") == 1
    assert cache_repo.get_transcript_sync_attempts(video_id="vid_block_2") == 0
    pause_until = cache_repo.get_cache_state_value("transcripts_background_ip_block_paused_until")
    assert pause_until is not None
    assert cache_repo.get_cache_state_value("transcripts_background_ip_block_streak") == "1"


def test_oauth_recent_probe_rate_limit_sets_pause_and_skips_api_while_paused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)
    service = YouTubeService(
        mode="oauth",
        data_dir=tmp_path,
        cache_repository=cache_repo,
    )

    calls: dict[str, int] = {"build_client": 0}

    def _failing_build_client(
        _data_dir: Path,
        *,
        token_path: Path | None = None,
        secrets_path: Path | None = None,
    ) -> object:
        _ = token_path
        _ = secrets_path
        calls["build_client"] += 1
        raise RuntimeError("quotaExceeded")

    monkeypatch.setattr(
        "backend.app.services.youtube_service._build_youtube_client",
        _failing_build_client,
    )

    with pytest.raises(YouTubeRateLimitedError) as first_exc:
        service.list_recent_cached_only_with_metadata(
            limit=5,
            query="missing term",
            probe_recent_on_miss=True,
            recent_probe_pages=1,
        )
    assert first_exc.value.scope == "youtube_data_api_recent_probe"
    assert first_exc.value.retry_after_seconds >= 900
    assert calls["build_client"] == 1
    assert (
        cache_repo.get_cache_state_value("likes_recent_probe_rate_limit_paused_until") is not None
    )
    assert cache_repo.get_cache_state_value("likes_recent_probe_rate_limit_streak") == "1"

    with pytest.raises(YouTubeRateLimitedError) as second_exc:
        service.list_recent_cached_only_with_metadata(
            limit=5,
            query="missing term",
            probe_recent_on_miss=True,
            recent_probe_pages=1,
        )
    assert second_exc.value.scope == "youtube_data_api_recent_probe"
    assert calls["build_client"] == 1
