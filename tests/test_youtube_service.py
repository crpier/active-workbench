from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from backend.app.services.youtube_service import (
    YouTubeService,
    YouTubeServiceError,
    resolve_oauth_paths,
)


def test_fixture_mode_likes_and_transcript(tmp_path: Path) -> None:
    service = YouTubeService(mode="fixture", data_dir=tmp_path)

    videos = service.list_recent(limit=2, query="cook")
    assert videos

    transcript = service.get_transcript(videos[0].video_id)
    assert transcript.transcript


def test_fixture_mode_natural_language_query_matches_keywords(tmp_path: Path) -> None:
    service = YouTubeService(mode="fixture", data_dir=tmp_path)

    videos = service.list_recent(
        limit=5,
        query="Somewhere I watched and liked a video about soup. Can you find it?",
    )
    assert videos
    assert any("soup" in video.title.lower() for video in videos)


def test_fixture_mode_query_without_match_returns_empty(tmp_path: Path) -> None:
    service = YouTubeService(mode="fixture", data_dir=tmp_path)

    videos = service.list_recent(limit=5, query="quantum cryptography lecture")
    assert videos == []


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


def test_resolve_oauth_paths_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACTIVE_WORKBENCH_YOUTUBE_TOKEN_PATH", raising=False)
    monkeypatch.delenv("ACTIVE_WORKBENCH_YOUTUBE_CLIENT_SECRET_PATH", raising=False)

    token_path, secret_path = resolve_oauth_paths(tmp_path)
    assert token_path == (tmp_path / "youtube-token.json").resolve()
    assert secret_path == (tmp_path / "youtube-client-secret.json").resolve()


def test_resolve_oauth_paths_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_override = tmp_path / "custom-token.json"
    secret_override = tmp_path / "custom-secret.json"
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_TOKEN_PATH", str(token_override))
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_CLIENT_SECRET_PATH", str(secret_override))

    token_path, secret_path = resolve_oauth_paths(tmp_path)
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
                            "snippet": {
                                "title": "OAuth Cooking",
                                "description": "fallback transcript",
                            }
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

    class FakeFetchedTranscript:
        def to_raw_data(self) -> list[dict[str, Any]]:
            return [{"text": "first line", "start": 0.0, "duration": 1.0}]

    class FakeTranscriptApi:
        def fetch(
            self,
            _video_id: str,
            languages: list[str] | None = None,
            preserve_formatting: bool = False,
        ) -> FakeFetchedTranscript:
            _ = languages
            _ = preserve_formatting
            return FakeFetchedTranscript()

    transcript_module = types.SimpleNamespace(YouTubeTranscriptApi=FakeTranscriptApi)
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", transcript_module)

    service = YouTubeService(mode="oauth", data_dir=tmp_path)
    videos = service.list_recent(limit=1)
    assert videos and videos[0].video_id == "oauth_video_1"
    assert videos[0].liked_at == "2026-02-01T12:00:00Z"

    transcript = service.get_transcript("oauth_video_1")
    assert "first line" in transcript.transcript

    class FailingTranscriptApi:
        def fetch(
            self,
            _video_id: str,
            languages: list[str] | None = None,
            preserve_formatting: bool = False,
        ) -> FakeFetchedTranscript:
            _ = languages
            _ = preserve_formatting
            raise RuntimeError("forced failure")

    transcript_module_failing = types.SimpleNamespace(YouTubeTranscriptApi=FailingTranscriptApi)
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", transcript_module_failing)

    fallback = service.get_transcript("oauth_video_1")
    assert fallback.source == "video_description_fallback"
