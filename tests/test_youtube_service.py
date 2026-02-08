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


def test_fixture_mode_history_and_transcript(tmp_path: Path) -> None:
    service = YouTubeService(mode="fixture", data_dir=tmp_path)

    videos = service.list_recent(limit=2, query="cook")
    assert videos

    transcript = service.get_transcript(videos[0].video_id)
    assert transcript.transcript


def test_oauth_mode_without_secrets_raises(tmp_path: Path) -> None:
    service = YouTubeService(mode="oauth", data_dir=tmp_path)

    with pytest.raises(YouTubeServiceError):
        service.list_recent(limit=1)


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

        def activities(self) -> FakeClient:
            return self

        def videos(self) -> FakeClient:
            return self

        def list(self, **kwargs: object) -> FakeClient:
            self._kwargs = kwargs
            return self

        def execute(self) -> dict[str, object]:
            kwargs = getattr(self, "_kwargs", {})
            if kwargs.get("mine") is True and "contentDetails,snippet" in str(kwargs.get("part")):
                return {
                    "items": [
                        {
                            "contentDetails": {
                                "relatedPlaylists": {"watchHistory": "HISTORY123"},
                            }
                        }
                    ]
                }
            if kwargs.get("playlistId") == "HISTORY123":
                return {
                    "items": [
                        {
                            "snippet": {
                                "resourceId": {"videoId": "oauth_video_1"},
                                "title": "OAuth Cooking",
                                "publishedAt": "2026-02-01T12:00:00Z",
                            }
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

    def _mock_get_transcript(
        _video_id: str,
        languages: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        _ = languages
        return [{"text": "first line", "start": 0.0, "duration": 1.0}]

    transcript_module = types.SimpleNamespace(
        YouTubeTranscriptApi=types.SimpleNamespace(get_transcript=_mock_get_transcript)
    )
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", transcript_module)

    service = YouTubeService(mode="oauth", data_dir=tmp_path)
    videos = service.list_recent(limit=1)
    assert videos and videos[0].video_id == "oauth_video_1"

    transcript = service.get_transcript("oauth_video_1")
    assert "first line" in transcript.transcript

    def _mock_get_transcript_failing(
        _video_id: str,
        languages: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        _ = languages
        raise RuntimeError("forced failure")

    transcript_module_failing = types.SimpleNamespace(
        YouTubeTranscriptApi=types.SimpleNamespace(get_transcript=_mock_get_transcript_failing)
    )
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", transcript_module_failing)

    fallback = service.get_transcript("oauth_video_1")
    assert fallback.source == "video_description_fallback"
