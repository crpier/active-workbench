from __future__ import annotations

import os
import re
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    published_at: str
    liked_at: str | None = None
    video_published_at: str | None = None
    description: str | None = None
    channel_title: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class YouTubeTranscript:
    video_id: str
    title: str
    transcript: str
    source: str
    segments: list[dict[str, Any]]


class YouTubeServiceError(Exception):
    pass


PREFERRED_TRANSCRIPT_LANGUAGES: tuple[str, ...] = (
    "en",
    "en-US",
    "en-GB",
    "ro",
    "de",
    "fr",
    "es",
    "it",
)

QUERY_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "am",
        "an",
        "are",
        "about",
        "and",
        "as",
        "at",
        "been",
        "but",
        "can",
        "could",
        "did",
        "do",
        "does",
        "find",
        "for",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "ive",
        "liked",
        "make",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "recently",
        "saw",
        "seen",
        "should",
        "some",
        "recent",
        "somewhere",
        "summarize",
        "summary",
        "that",
        "tell",
        "the",
        "them",
        "then",
        "there",
        "this",
        "to",
        "up",
        "video",
        "want",
        "was",
        "watched",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "would",
        "you",
    }
)


FIXTURE_VIDEOS: list[YouTubeVideo] = [
    YouTubeVideo(
        video_id="fixture_cooking_001",
        title="How To Cook Leek And Potato Soup",
        published_at="2026-02-06T18:00:00+00:00",
        liked_at="2026-02-06T18:00:00+00:00",
        video_published_at="2026-02-06T18:00:00+00:00",
        description="Simple leek soup tutorial with potato and stock.",
        channel_title="Fixture Cooking",
        tags=("soup", "leek", "recipe"),
    ),
    YouTubeVideo(
        video_id="fixture_micro_001",
        title="Microservices Done Right - Real Lessons",
        published_at="2026-02-05T19:30:00+00:00",
        liked_at="2026-02-05T19:30:00+00:00",
        video_published_at="2026-02-05T19:30:00+00:00",
        description="Architecture trade-offs and distributed systems pitfalls.",
        channel_title="Fixture Engineering",
        tags=("microservices", "architecture"),
    ),
    YouTubeVideo(
        video_id="fixture_general_001",
        title="Weekly Productivity Systems",
        published_at="2026-02-04T15:00:00+00:00",
        liked_at="2026-02-04T15:00:00+00:00",
        video_published_at="2026-02-04T15:00:00+00:00",
        description="A review of GPT-5.3 pros and cons for coding productivity.",
        channel_title="Fixture AI",
        tags=("gpt-5.3", "llm", "productivity"),
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

    @property
    def is_oauth_mode(self) -> bool:
        return self._mode == "oauth"

    def list_recent(self, limit: int, query: str | None = None) -> list[YouTubeVideo]:
        if self._mode != "oauth":
            return _filter_fixture_videos(limit=limit, query=query)

        oauth_videos = self._list_recent_oauth(limit=limit, enrich_metadata=query is not None)
        if query is None:
            return oauth_videos

        filtered = _filter_videos_by_query(oauth_videos, query)
        return filtered[:limit]

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

    def _list_recent_oauth(self, limit: int, *, enrich_metadata: bool) -> list[YouTubeVideo]:
        client = _build_youtube_client(self._data_dir)

        try:
            videos = _list_from_liked_videos(client, limit, enrich_metadata=enrich_metadata)
        except Exception as exc:
            raise YouTubeServiceError(
                f"Failed to fetch liked videos for OAuth user: {exc}"
            ) from exc

        if not videos:
            raise YouTubeServiceError("No liked videos available for this OAuth account.")

        return videos[:limit]

    def _fetch_transcript_with_api(self, video_id: str) -> YouTubeTranscript | None:
        title = _fetch_video_title(video_id, self._data_dir)

        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            transcript_api = cast(Any, YouTubeTranscriptApi)
            segments_raw = _fetch_captions_segments(video_id, transcript_api)

            text = "\n".join(str(segment.get("text", "")) for segment in segments_raw).strip()
            if text:
                parsed_segments = _normalize_segments(segments_raw)

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

    filtered = _filter_videos_by_query(FIXTURE_VIDEOS, query)
    return filtered[:limit]


def _filter_videos_by_query(videos: list[YouTubeVideo], query: str) -> list[YouTubeVideo]:
    normalized_query = query.lower().strip()
    if not normalized_query:
        return videos

    direct_matches = [
        video
        for video in videos
        if normalized_query in _video_search_text(video)
    ]
    if direct_matches:
        return direct_matches

    query_tokens = _query_tokens(normalized_query)
    if not query_tokens:
        return []

    scored: list[tuple[int, int, YouTubeVideo]] = []
    for index, video in enumerate(videos):
        score = _score_video_against_query(video, query_tokens)
        if score > 0:
            scored.append((score, -index, video))

    scored.sort(reverse=True)
    return [video for _, _, video in scored]


def _query_tokens(query: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", query)
    return [token for token in tokens if len(token) >= 3 and token not in QUERY_STOPWORDS]


def _score_video_against_query(video: YouTubeVideo, query_tokens: list[str]) -> int:
    search_text = _video_search_text(video)
    search_tokens = set(re.findall(r"[a-z0-9]+", search_text))

    score = 0
    for token in query_tokens:
        if token in search_tokens:
            score += 3
        elif token in search_text:
            score += 1
    return score


def _video_search_text(video: YouTubeVideo) -> str:
    parts = [
        video.title,
        video.description or "",
        video.channel_title or "",
        " ".join(video.tags),
    ]
    return " ".join(parts).lower()


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


def _list_from_liked_videos(
    client: Any,
    limit: int,
    *,
    enrich_metadata: bool,
) -> list[YouTubeVideo]:
    likes_playlist_id = _resolve_likes_playlist_id(client)

    response = cast(
        dict[str, Any],
        client.playlistItems()
        .list(
            part="snippet,contentDetails",
            playlistId=likes_playlist_id,
            maxResults=min(limit, 50),
        )
        .execute(),
    )

    videos: list[YouTubeVideo] = []
    items = _as_list(response.get("items"))
    for item in items:
        item_dict = _as_dict(item)
        content_details = _as_dict(item_dict.get("contentDetails"))
        snippet = _as_dict(item_dict.get("snippet"))
        resource = _as_dict(snippet.get("resourceId"))
        video_id = resource.get("videoId")
        title = snippet.get("title")
        liked_at = snippet.get("publishedAt")
        video_published_at_value = content_details.get("videoPublishedAt")
        video_published_at = (
            video_published_at_value if isinstance(video_published_at_value, str) else None
        )

        if isinstance(video_id, str) and isinstance(title, str) and isinstance(liked_at, str):
            videos.append(
                YouTubeVideo(
                    video_id=video_id,
                    title=title,
                    published_at=liked_at,
                    liked_at=liked_at,
                    video_published_at=video_published_at,
                )
            )

    if enrich_metadata and videos:
        return _enrich_liked_video_metadata(client, videos)

    return videos


def _enrich_liked_video_metadata(client: Any, videos: list[YouTubeVideo]) -> list[YouTubeVideo]:
    video_ids = [video.video_id for video in videos]
    response = cast(
        dict[str, Any],
        client.videos()
        .list(
            part="snippet",
            id=",".join(video_ids),
            maxResults=min(50, len(video_ids)),
        )
        .execute(),
    )

    metadata_by_id: dict[str, tuple[str | None, str | None, tuple[str, ...]]] = {}
    for item in _as_list(response.get("items")):
        item_dict = _as_dict(item)
        raw_video_id = item_dict.get("id")
        if not isinstance(raw_video_id, str):
            continue

        snippet = _as_dict(item_dict.get("snippet"))
        description_raw = snippet.get("description")
        description = description_raw if isinstance(description_raw, str) else None

        channel_raw = snippet.get("channelTitle")
        channel_title = channel_raw if isinstance(channel_raw, str) else None

        tags_raw = snippet.get("tags")
        tags: tuple[str, ...] = ()
        if isinstance(tags_raw, list):
            values: list[str] = []
            for raw_tag in cast(list[Any], tags_raw):
                if isinstance(raw_tag, str):
                    values.append(raw_tag)
            tags = tuple(values)

        metadata_by_id[raw_video_id] = (description, channel_title, tags)

    enriched: list[YouTubeVideo] = []
    for video in videos:
        description, channel_title, tags = metadata_by_id.get(video.video_id, (None, None, ()))
        enriched.append(
            YouTubeVideo(
                video_id=video.video_id,
                title=video.title,
                published_at=video.published_at,
                liked_at=video.liked_at,
                video_published_at=video.video_published_at,
                description=description,
                channel_title=channel_title,
                tags=tags,
            )
        )
    return enriched


def _resolve_likes_playlist_id(client: Any) -> str:
    response = cast(
        dict[str, Any],
        client.channels().list(part="contentDetails", mine=True, maxResults=1).execute(),
    )

    items = _as_list(response.get("items"))
    if not items:
        return "LL"

    first_item = _as_dict(items[0])
    content_details = _as_dict(first_item.get("contentDetails"))
    related = _as_dict(content_details.get("relatedPlaylists"))
    likes_value = related.get("likes")
    if isinstance(likes_value, str) and likes_value.strip():
        return likes_value
    return "LL"


def _fetch_captions_segments(video_id: str, transcript_api_ref: Any) -> list[dict[str, Any]]:
    preferred_languages = list(PREFERRED_TRANSCRIPT_LANGUAGES)
    api_instance = _build_transcript_api_instance(transcript_api_ref)

    fetch_callable = getattr(api_instance, "fetch", None)
    if callable(fetch_callable):
        try:
            fetched = fetch_callable(
                video_id,
                languages=preferred_languages,
                preserve_formatting=False,
            )
            segments = _normalize_segments(fetched)
            if segments:
                return segments
        except Exception:
            pass

    list_callable = getattr(api_instance, "list", None)
    if callable(list_callable):
        try:
            transcript_list = list_callable(video_id)
            selected = _select_transcript_track(transcript_list, preferred_languages)
            if selected is not None:
                track_fetch = getattr(selected, "fetch", None)
                if callable(track_fetch):
                    fetched = track_fetch()
                    segments = _normalize_segments(fetched)
                    if segments:
                        return segments
        except Exception:
            pass

    legacy_get = getattr(transcript_api_ref, "get_transcript", None)
    if callable(legacy_get):
        legacy_segments = legacy_get(video_id, languages=preferred_languages)
        return _normalize_segments(legacy_segments)

    legacy_get_instance = getattr(api_instance, "get_transcript", None)
    if callable(legacy_get_instance):
        legacy_segments = legacy_get_instance(video_id, languages=preferred_languages)
        return _normalize_segments(legacy_segments)

    return []


def _build_transcript_api_instance(transcript_api_ref: Any) -> Any:
    try:
        return transcript_api_ref()
    except Exception:
        return transcript_api_ref


def _select_transcript_track(transcript_list: Any, preferred_languages: list[str]) -> Any | None:
    for selector_name in (
        "find_manually_created_transcript",
        "find_generated_transcript",
        "find_transcript",
    ):
        selector = getattr(transcript_list, selector_name, None)
        if callable(selector):
            try:
                track = selector(preferred_languages)
                if track is not None:
                    return track
            except Exception:
                continue

    try:
        for track in transcript_list:
            return track
    except Exception:
        return None

    return None


def _normalize_segments(raw_segments: Any) -> list[dict[str, Any]]:
    to_raw_data = getattr(raw_segments, "to_raw_data", None)
    if callable(to_raw_data):
        raw_segments = to_raw_data()

    segments: list[dict[str, Any]] = []
    for raw_segment in _iterable_items(raw_segments):
        segment_dict = _segment_to_dict(raw_segment)
        if segment_dict is not None:
            segments.append(segment_dict)
    return segments


def _iterable_items(raw_value: Any) -> list[Any]:
    if isinstance(raw_value, list):
        raw_list = cast(list[Any], raw_value)
        return list(raw_list)
    if isinstance(raw_value, tuple):
        raw_tuple = cast(tuple[Any, ...], raw_value)
        return list(raw_tuple)

    try:
        iterator: Any = iter(raw_value)
    except Exception:
        return []

    items: list[Any] = []
    for item in iterator:
        items.append(item)
    return items


def _segment_to_dict(raw_segment: Any) -> dict[str, Any] | None:
    if isinstance(raw_segment, dict):
        source = cast(dict[object, object], raw_segment)
        text = source.get("text")
        start = source.get("start")
        duration = source.get("duration")
    else:
        text = getattr(raw_segment, "text", None)
        start = getattr(raw_segment, "start", None)
        duration = getattr(raw_segment, "duration", None)

    if not isinstance(text, str):
        return None

    return {
        "text": text,
        "start": _coerce_float(start),
        "duration": _coerce_float(duration),
    }


def _coerce_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


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
