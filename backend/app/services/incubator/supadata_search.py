from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SupadataSearchQuery:
    """
    Planned input contract for future Supadata search integration.
    """

    query: str
    max_results: int = 10
    preferred_language: str = "ro"


@dataclass(frozen=True)
class SupadataSearchHit:
    """
    Planned output shape for a single search result.
    """

    video_id: str
    title: str
    channel_title: str | None = None
    published_at: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class SupadataSearchResult:
    """
    Planned output contract for the search tool.
    """

    hits: tuple[SupadataSearchHit, ...]
    provider_request_id: str | None = None


class SupadataSearchService:
    """
    Incubator placeholder for future Supadata search capabilities.

    This class intentionally does not call any API yet. It gives us a stable
    place to add the real implementation and wire a tool when we're ready.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.supadata.ai/v1",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = max(1.0, timeout_seconds)

    def search_videos(self, query: SupadataSearchQuery) -> SupadataSearchResult:
        raise NotImplementedError(
            "Supadata search is in the incubator. Tool wiring and provider mapping "
            "are intentionally pending."
        )
