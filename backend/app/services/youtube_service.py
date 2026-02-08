from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    published_at: str


@dataclass(frozen=True)
class YouTubeTranscript:
    video_id: str
    title: str
    transcript: str
    source: str
    segments: list[dict[str, Any]]


class YouTubeServiceError(Exception):
    pass


FIXTURE_VIDEOS: list[YouTubeVideo] = [
    YouTubeVideo(
        video_id="fixture_cooking_001",
        title="How To Cook Leek And Potato Soup",
        published_at="2026-02-06T18:00:00+00:00",
    ),
    YouTubeVideo(
        video_id="fixture_micro_001",
        title="Microservices Done Right - Real Lessons",
        published_at="2026-02-05T19:30:00+00:00",
    ),
    YouTubeVideo(
        video_id="fixture_general_001",
        title="Weekly Productivity Systems",
        published_at="2026-02-04T15:00:00+00:00",
    ),
]

FIXTURE_TRANSCRIPTS: dict[str, YouTubeTranscript] = {
    "fixture_cooking_001": YouTubeTranscript(
        video_id="fixture_cooking_001",
        title="How To Cook Leek And Potato Soup",
        source="fixture",
        transcript="""
Today we're cooking a leek and potato soup.
Ingredients: 2 leeks, 3 potatoes, 2 tbsp olive oil, 1 liter vegetable stock, salt, pepper.
Chop the leeks and potatoes.
Heat oil in a pot and add chopped leeks. Stir for 5 minutes.
Add potatoes and stock, then simmer for 25 minutes.
Blend until smooth, add salt and pepper, and serve warm.
""".strip(),
        segments=[],
    ),
    "fixture_micro_001": YouTubeTranscript(
        video_id="fixture_micro_001",
        title="Microservices Done Right - Real Lessons",
        source="fixture",
        transcript="""
Microservices help teams deploy independently, but they increase operational complexity.
Start with clear service boundaries and avoid sharing databases.
Observability is critical: tracing, metrics, and logs must be designed from day one.
Failure isolation and retries are useful, but uncontrolled retries can create cascading failures.
Use asynchronous messaging when latency tolerance allows it.
""".strip(),
        segments=[],
    ),
}


class YouTubeService:
    def __init__(self, mode: str, data_dir: Path) -> None:
        self._mode = mode
        self._data_dir = data_dir

    def list_recent(self, limit: int, query: str | None = None) -> list[YouTubeVideo]:
        if self._mode != "oauth":
            return _filter_fixture_videos(limit=limit, query=query)

        oauth_videos = self._list_recent_oauth(limit=limit)
        if query is None:
            return oauth_videos

        filtered = [video for video in oauth_videos if query.lower() in video.title.lower()]
        if filtered:
            return filtered[:limit]
        return oauth_videos[:limit]

    def get_transcript(self, video_id: str) -> YouTubeTranscript:
        if self._mode != "oauth":
            transcript = FIXTURE_TRANSCRIPTS.get(video_id)
            if transcript is None:
                raise YouTubeServiceError(f"No fixture transcript found for video_id={video_id}")
            return transcript

        transcript = self._fetch_transcript_with_api(video_id)
        if transcript is not None:
            return transcript

        raise YouTubeServiceError(
            "Transcript unavailable from YouTube captions and no fallback provider succeeded"
        )

    def _list_recent_oauth(self, limit: int) -> list[YouTubeVideo]:
        client = _build_youtube_client(self._data_dir)

        try:
            channels_resp = cast(
                dict[str, Any],
                client.channels().list(part="contentDetails,snippet", mine=True).execute(),
            )
        except Exception as exc:
            raise YouTubeServiceError(f"Failed to fetch channels for OAuth user: {exc}") from exc

        items = _as_list(channels_resp.get("items"))
        if not items:
            raise YouTubeServiceError("OAuth account has no accessible YouTube channels")

        first_item = _as_dict(items[0])
        content_details = _as_dict(first_item.get("contentDetails"))
        related = _as_dict(content_details.get("relatedPlaylists"))
        history_playlist_value = related.get("watchHistory")

        videos: list[YouTubeVideo] = []
        if isinstance(history_playlist_value, str) and history_playlist_value:
            videos = _list_from_history_playlist(client, history_playlist_value, limit)

        if not videos:
            videos = _list_from_recent_activities(client, limit)

        if not videos:
            raise YouTubeServiceError("No recent videos available from OAuth user activity")

        return videos[:limit]

    def _fetch_transcript_with_api(self, video_id: str) -> YouTubeTranscript | None:
        title = _fetch_video_title(video_id, self._data_dir)

        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            transcript_api = cast(Any, YouTubeTranscriptApi)
            segments_raw = cast(
                list[dict[str, Any]],
                transcript_api.get_transcript(video_id, languages=["en", "en-US", "en-GB"]),
            )

            text = "\n".join(str(segment.get("text", "")) for segment in segments_raw)

            parsed_segments: list[dict[str, Any]] = []
            for segment in segments_raw:
                parsed_segments.append(
                    {
                        "text": str(segment.get("text", "")),
                        "start": float(segment.get("start", 0.0)),
                        "duration": float(segment.get("duration", 0.0)),
                    }
                )

            return YouTubeTranscript(
                video_id=video_id,
                title=title,
                transcript=text,
                source="youtube_captions",
                segments=parsed_segments,
            )
        except Exception:
            pass

        description = _fetch_video_description(video_id, self._data_dir)
        if description is None:
            return None

        return YouTubeTranscript(
            video_id=video_id,
            title=title,
            transcript=description,
            source="video_description_fallback",
            segments=[],
        )


def _filter_fixture_videos(limit: int, query: str | None) -> list[YouTubeVideo]:
    if query is None:
        return FIXTURE_VIDEOS[:limit]

    lower_query = query.lower().strip()
    filtered = [video for video in FIXTURE_VIDEOS if lower_query in video.title.lower()]
    if filtered:
        return filtered[:limit]
    return FIXTURE_VIDEOS[:limit]


def _build_youtube_client(data_dir: Path) -> Any:
    try:
        requests_module = import_module("google.auth.transport.requests")
        credentials_module = import_module("google.oauth2.credentials")
        flow_module = import_module("google_auth_oauthlib.flow")
        discovery_module = import_module("googleapiclient.discovery")
    except ImportError as exc:  # pragma: no cover - dependency controlled at runtime
        raise YouTubeServiceError(
            "OAuth mode requires google-api-python-client and google-auth-oauthlib dependencies"
        ) from exc

    scope = ["https://www.googleapis.com/auth/youtube.readonly"]
    token_path, secrets_path = resolve_oauth_paths(data_dir)

    request_cls: Any = requests_module.Request
    credentials_cls: Any = credentials_module.Credentials
    flow_cls: Any = flow_module.InstalledAppFlow
    build_fn: Any = discovery_module.build

    credentials: Any | None = None
    if token_path.exists():
        credentials = credentials_cls.from_authorized_user_file(str(token_path), scope)

    if credentials is None or not credentials.valid:
        if credentials is not None and credentials.expired and credentials.refresh_token:
            credentials.refresh(request_cls())
        else:
            if not secrets_path.exists():
                raise YouTubeServiceError(f"Missing OAuth client secret file at {secrets_path}")

            flow = flow_cls.from_client_secrets_file(str(secrets_path), scope)
            credentials = flow.run_local_server(port=0)

        if credentials is None:
            raise YouTubeServiceError("OAuth flow did not return credentials")

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(str(credentials.to_json()), encoding="utf-8")

    return build_fn("youtube", "v3", credentials=credentials, cache_discovery=False)


def resolve_oauth_paths(data_dir: Path) -> tuple[Path, Path]:
    token_override = os.getenv("ACTIVE_WORKBENCH_YOUTUBE_TOKEN_PATH")
    secret_override = os.getenv("ACTIVE_WORKBENCH_YOUTUBE_CLIENT_SECRET_PATH")

    token_path = (
        Path(token_override).expanduser().resolve()
        if token_override
        else (data_dir / "youtube-token.json").resolve()
    )
    secrets_path = (
        Path(secret_override).expanduser().resolve()
        if secret_override
        else (data_dir / "youtube-client-secret.json").resolve()
    )
    return token_path, secrets_path


def _list_from_history_playlist(client: Any, playlist_id: str, limit: int) -> list[YouTubeVideo]:
    response = cast(
        dict[str, Any],
        client.playlistItems()
        .list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=min(limit, 50),
        )
        .execute(),
    )

    videos: list[YouTubeVideo] = []
    items = _as_list(response.get("items"))
    for item in items:
        item_dict = _as_dict(item)
        snippet = _as_dict(item_dict.get("snippet"))
        resource = _as_dict(snippet.get("resourceId"))
        video_id = resource.get("videoId")
        title = snippet.get("title")
        published_at = snippet.get("publishedAt")

        if isinstance(video_id, str) and isinstance(title, str) and isinstance(published_at, str):
            videos.append(YouTubeVideo(video_id=video_id, title=title, published_at=published_at))

    return videos


def _list_from_recent_activities(client: Any, limit: int) -> list[YouTubeVideo]:
    response = cast(
        dict[str, Any],
        client.activities()
        .list(part="snippet,contentDetails", mine=True, maxResults=limit)
        .execute(),
    )

    videos: list[YouTubeVideo] = []
    items = _as_list(response.get("items"))
    for item in items:
        item_dict = _as_dict(item)
        snippet = _as_dict(item_dict.get("snippet"))
        details = _as_dict(item_dict.get("contentDetails"))
        upload = _as_dict(details.get("upload"))
        video_id = upload.get("videoId")
        title = snippet.get("title")
        published_at = snippet.get("publishedAt")

        if isinstance(video_id, str) and isinstance(title, str) and isinstance(published_at, str):
            videos.append(YouTubeVideo(video_id=video_id, title=title, published_at=published_at))

    return videos


def _fetch_video_title(video_id: str, data_dir: Path) -> str:
    client = _build_youtube_client(data_dir)
    response = cast(
        dict[str, Any],
        client.videos().list(part="snippet", id=video_id, maxResults=1).execute(),
    )

    items = _as_list(response.get("items"))
    if items:
        snippet = _as_dict(_as_dict(items[0]).get("snippet"))
        title = snippet.get("title")
        if isinstance(title, str) and title.strip():
            return title
    return video_id


def _fetch_video_description(video_id: str, data_dir: Path) -> str | None:
    client = _build_youtube_client(data_dir)
    response = cast(
        dict[str, Any],
        client.videos().list(part="snippet", id=video_id, maxResults=1).execute(),
    )

    items = _as_list(response.get("items"))
    if not items:
        return None

    snippet = _as_dict(_as_dict(items[0]).get("snippet"))
    description = snippet.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        raw_dict = cast(dict[object, object], value)
        converted: dict[str, Any] = {}
        for key, item in raw_dict.items():
            if isinstance(key, str):
                converted[key] = item
        return converted
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        raw_list = cast(list[Any], value)
        return list(raw_list)
    return []
