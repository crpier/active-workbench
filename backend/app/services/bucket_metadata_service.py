from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from backend.app.repositories.bucket_bookwyrm_quota_repository import (
    BucketBookwyrmQuotaRepository,
)
from backend.app.repositories.bucket_musicbrainz_quota_repository import (
    BucketMusicbrainzQuotaRepository,
)
from backend.app.repositories.bucket_tmdb_quota_repository import BucketTmdbQuotaRepository


@dataclass(frozen=True)
class BucketEnrichment:
    canonical_id: str | None
    year: int | None
    duration_minutes: int | None
    rating: float | None
    popularity: float | None
    genres: list[str]
    tags: list[str]
    providers: list[str]
    external_url: str | None
    confidence: float | None
    metadata: dict[str, Any]
    source_refs: list[dict[str, str]]
    provider: str | None


@dataclass(frozen=True)
class BucketResolveCandidate:
    canonical_id: str
    provider: Literal["tmdb", "bookwyrm", "musicbrainz"]
    title: str
    year: int | None
    confidence: float
    external_url: str
    tmdb_id: int | None = None
    media_type: Literal["movie", "tv", "book", "music"] | None = None
    popularity: float | None = None
    vote_count: int | None = None
    bookwyrm_key: str | None = None
    author: str | None = None
    musicbrainz_release_group_id: str | None = None
    artist: str | None = None


@dataclass(frozen=True)
class BucketAddResolution:
    status: Literal["resolved", "ambiguous", "no_match", "rate_limited", "skipped"]
    reason: str | None
    selected_candidate: BucketResolveCandidate | None
    candidates: list[BucketResolveCandidate]
    enrichment: BucketEnrichment | None
    retry_after_seconds: float | None


@dataclass(frozen=True)
class _TmdbRequest:
    payload: dict[str, Any] | None
    rate_limited: bool
    retry_after_seconds: float | None


@dataclass(frozen=True)
class _BookwyrmSearchRequest:
    payload: list[dict[str, Any]] | None
    rate_limited: bool
    retry_after_seconds: float | None


@dataclass(frozen=True)
class _BookwyrmDetailRequest:
    payload: dict[str, Any] | None
    rate_limited: bool
    retry_after_seconds: float | None


@dataclass(frozen=True)
class _MusicbrainzRequest:
    payload: dict[str, Any] | None
    rate_limited: bool
    retry_after_seconds: float | None


class BucketMetadataService:
    def __init__(
        self,
        *,
        enrichment_enabled: bool,
        http_timeout_seconds: float,
        tmdb_api_key: str | None,
        tmdb_quota_repository: BucketTmdbQuotaRepository | None = None,
        tmdb_daily_soft_limit: int = 500,
        tmdb_min_interval_seconds: float = 1.1,
        bookwyrm_base_url: str = "https://bookwyrm.social",
        bookwyrm_user_agent: str = "active-workbench/0.1 (+https://github.com/crpier/active-workbench)",
        bookwyrm_quota_repository: BucketBookwyrmQuotaRepository | None = None,
        bookwyrm_daily_soft_limit: int = 500,
        bookwyrm_min_interval_seconds: float = 1.1,
        musicbrainz_base_url: str = "https://musicbrainz.org",
        musicbrainz_user_agent: str = "active-workbench/0.1 (+https://github.com/crpier/active-workbench)",
        musicbrainz_quota_repository: BucketMusicbrainzQuotaRepository | None = None,
        musicbrainz_daily_soft_limit: int = 500,
        musicbrainz_min_interval_seconds: float = 1.1,
    ) -> None:
        self._enrichment_enabled = enrichment_enabled
        self._http_timeout_seconds = max(0.5, http_timeout_seconds)
        self._tmdb_api_key = _normalize_optional_text(tmdb_api_key)
        self._tmdb_quota_repository = tmdb_quota_repository
        self._tmdb_daily_soft_limit = max(0, tmdb_daily_soft_limit)
        self._tmdb_min_interval_seconds = max(0.0, tmdb_min_interval_seconds)
        self._bookwyrm_base_url = _normalize_base_url(
            bookwyrm_base_url,
            fallback="https://bookwyrm.social",
        )
        self._bookwyrm_user_agent = _normalize_optional_text(bookwyrm_user_agent) or (
            "active-workbench/0.1 (+https://github.com/crpier/active-workbench)"
        )
        self._bookwyrm_quota_repository = bookwyrm_quota_repository
        self._bookwyrm_daily_soft_limit = max(0, bookwyrm_daily_soft_limit)
        self._bookwyrm_min_interval_seconds = max(0.0, bookwyrm_min_interval_seconds)
        self._musicbrainz_base_url = _normalize_base_url(
            musicbrainz_base_url,
            fallback="https://musicbrainz.org",
        )
        self._musicbrainz_user_agent = _normalize_optional_text(musicbrainz_user_agent) or (
            "active-workbench/0.1 (+https://github.com/crpier/active-workbench)"
        )
        self._musicbrainz_quota_repository = musicbrainz_quota_repository
        self._musicbrainz_daily_soft_limit = max(0, musicbrainz_daily_soft_limit)
        self._musicbrainz_min_interval_seconds = max(0.0, musicbrainz_min_interval_seconds)

    def resolve_for_bucket_add(
        self,
        *,
        title: str,
        domain: str,
        year: int | None,
        artist_hint: str | None = None,
        tmdb_id: int | None = None,
        bookwyrm_key: str | None = None,
        musicbrainz_release_group_id: str | None = None,
        max_candidates: int = 5,
    ) -> BucketAddResolution:
        normalized_domain = domain.strip().lower()
        if not self._enrichment_enabled:
            return BucketAddResolution(
                status="skipped",
                reason="enrichment_disabled",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=None,
            )
        if normalized_domain == "book":
            return self._resolve_bookwyrm_for_bucket_add(
                title=title,
                year=year,
                bookwyrm_key=bookwyrm_key,
                max_candidates=max_candidates,
            )
        if normalized_domain == "music":
            return self._resolve_musicbrainz_for_bucket_add(
                title=title,
                year=year,
                artist_hint=artist_hint,
                musicbrainz_release_group_id=musicbrainz_release_group_id,
                max_candidates=max_candidates,
            )

        media_type = _tmdb_media_type_for_domain(normalized_domain)
        if media_type is None:
            return BucketAddResolution(
                status="skipped",
                reason="unsupported_domain",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=None,
            )
        return self._resolve_tmdb_for_bucket_add(
            title=title,
            media_type=media_type,
            year=year,
            tmdb_id=tmdb_id,
            max_candidates=max_candidates,
        )

    def enrich(
        self,
        *,
        title: str,
        domain: str,
        year: int | None,
    ) -> BucketEnrichment:
        normalized_domain = domain.strip().lower()
        if not self._enrichment_enabled:
            return _empty_enrichment()
        if normalized_domain == "book":
            enriched_book = self._enrich_with_bookwyrm(title=title, year=year)
            if enriched_book is not None:
                return enriched_book
            return _empty_enrichment()
        if normalized_domain == "music":
            enriched_music = self._enrich_with_musicbrainz(title=title, year=year)
            if enriched_music is not None:
                return enriched_music
            return _empty_enrichment()
        if normalized_domain not in {"movie", "tv", "show"}:
            return _empty_enrichment()

        if self._tmdb_api_key is not None:
            enriched_tmdb = self._enrich_with_tmdb(
                title=title,
                domain=normalized_domain,
                year=year,
            )
            if enriched_tmdb is not None:
                return enriched_tmdb

        enriched_itunes = self._enrich_with_itunes(title=title, domain=normalized_domain)
        if enriched_itunes is not None:
            return enriched_itunes

        return _empty_enrichment()

    def _enrich_with_tmdb(
        self,
        *,
        title: str,
        domain: str,
        year: int | None,
    ) -> BucketEnrichment | None:
        if self._tmdb_api_key is None:
            return None
        resolution = self.resolve_for_bucket_add(
            title=title,
            domain=domain,
            year=year,
            tmdb_id=None,
            max_candidates=5,
        )
        if resolution.status != "resolved" or resolution.enrichment is None:
            return None
        return resolution.enrichment

    def _resolve_tmdb_for_bucket_add(
        self,
        *,
        title: str,
        media_type: Literal["movie", "tv"],
        year: int | None,
        tmdb_id: int | None,
        max_candidates: int,
    ) -> BucketAddResolution:
        year_hint = year if year is not None else _parse_year(title)
        if self._tmdb_api_key is None:
            return BucketAddResolution(
                status="skipped",
                reason="tmdb_key_missing",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=None,
            )

        if tmdb_id is not None:
            detail_request = self._fetch_tmdb_details(media_type=media_type, tmdb_id=tmdb_id)
            if detail_request.rate_limited:
                return BucketAddResolution(
                    status="rate_limited",
                    reason="tmdb_rate_limited",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=detail_request.retry_after_seconds,
                )
            if detail_request.payload is None:
                return BucketAddResolution(
                    status="no_match",
                    reason="tmdb_id_not_found",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=None,
                )

            selected_candidate = _candidate_from_tmdb_detail(
                detail_request.payload,
                media_type=media_type,
                query_title=title,
            )
            if selected_candidate is None:
                return BucketAddResolution(
                    status="no_match",
                    reason="tmdb_id_not_found",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=None,
                )

            enrichment = _enrichment_from_tmdb_payload(
                payload=detail_request.payload,
                media_type=media_type,
                query_title=title,
            )
            if enrichment is None:
                return BucketAddResolution(
                    status="no_match",
                    reason="tmdb_id_not_found",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=None,
                )
            return BucketAddResolution(
                status="resolved",
                reason="resolved_from_tmdb_id",
                selected_candidate=selected_candidate,
                candidates=[],
                enrichment=enrichment,
                retry_after_seconds=None,
            )

        search_request = self._search_tmdb(title=title, media_type=media_type, year=year_hint)
        if search_request.rate_limited:
            return BucketAddResolution(
                status="rate_limited",
                reason="tmdb_rate_limited",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=search_request.retry_after_seconds,
            )
        if search_request.payload is None:
            return BucketAddResolution(
                status="no_match",
                reason="tmdb_search_unavailable",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=None,
            )

        candidates = _tmdb_search_candidates(
            payload=search_request.payload,
            media_type=media_type,
            query_title=title,
            query_year=year_hint,
            max_candidates=max(1, max_candidates),
        )
        if not candidates:
            return BucketAddResolution(
                status="no_match",
                reason="no_candidate_match",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=None,
            )

        if not _should_auto_resolve(candidates):
            return BucketAddResolution(
                status="ambiguous",
                reason="ambiguous_match",
                selected_candidate=None,
                candidates=candidates,
                enrichment=None,
                retry_after_seconds=None,
            )

        selected = candidates[0]
        selected_tmdb_id = selected.tmdb_id
        selected_media_type = selected.media_type
        if selected_tmdb_id is None or selected_media_type not in {"movie", "tv"}:
            return BucketAddResolution(
                status="ambiguous",
                reason="details_unavailable",
                selected_candidate=None,
                candidates=candidates,
                enrichment=None,
                retry_after_seconds=None,
            )
        tmdb_media_type = cast(Literal["movie", "tv"], selected_media_type)
        search_item = _tmdb_search_item_by_id(
            payload=search_request.payload,
            tmdb_id=selected_tmdb_id,
        )
        if search_item is None:
            return BucketAddResolution(
                status="ambiguous",
                reason="details_unavailable",
                selected_candidate=None,
                candidates=candidates,
                enrichment=None,
                retry_after_seconds=None,
            )

        enrichment = _enrichment_from_tmdb_search_item(
            payload=search_item,
            media_type=tmdb_media_type,
            query_title=title,
        )
        if enrichment is None:
            return BucketAddResolution(
                status="ambiguous",
                reason="details_unavailable",
                selected_candidate=None,
                candidates=candidates,
                enrichment=None,
                retry_after_seconds=None,
            )
        return BucketAddResolution(
            status="resolved",
            reason="high_confidence_match",
            selected_candidate=selected,
            candidates=candidates,
            enrichment=enrichment,
            retry_after_seconds=None,
        )

    def _resolve_bookwyrm_for_bucket_add(
        self,
        *,
        title: str,
        year: int | None,
        bookwyrm_key: str | None,
        max_candidates: int,
    ) -> BucketAddResolution:
        year_hint = year if year is not None else _parse_year(title)
        normalized_key = _normalize_bookwyrm_key(bookwyrm_key)
        if normalized_key is not None:
            detail_request = self._fetch_bookwyrm_details(key=normalized_key)
            if detail_request.rate_limited:
                return BucketAddResolution(
                    status="rate_limited",
                    reason="bookwyrm_rate_limited",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=detail_request.retry_after_seconds,
                )
            if detail_request.payload is None:
                return BucketAddResolution(
                    status="no_match",
                    reason="bookwyrm_key_not_found",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=None,
                )

            selected_candidate = _candidate_from_bookwyrm_detail(
                payload=detail_request.payload,
                query_title=title,
                query_year=year_hint,
                fallback_key=normalized_key,
            )
            if selected_candidate is None:
                return BucketAddResolution(
                    status="no_match",
                    reason="bookwyrm_key_not_found",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=None,
                )
            enrichment = _enrichment_from_bookwyrm_payload(
                payload=detail_request.payload,
                query_title=title,
                query_year=year_hint,
                fallback_key=normalized_key,
                fallback_author=None,
            )
            if enrichment is None:
                return BucketAddResolution(
                    status="no_match",
                    reason="bookwyrm_key_not_found",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=None,
                )
            return BucketAddResolution(
                status="resolved",
                reason="resolved_from_bookwyrm_key",
                selected_candidate=selected_candidate,
                candidates=[],
                enrichment=enrichment,
                retry_after_seconds=None,
            )

        search_request = self._search_bookwyrm(title=title)
        if search_request.rate_limited:
            return BucketAddResolution(
                status="rate_limited",
                reason="bookwyrm_rate_limited",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=search_request.retry_after_seconds,
            )
        if search_request.payload is None:
            return BucketAddResolution(
                status="no_match",
                reason="bookwyrm_search_unavailable",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=None,
            )

        candidates = _bookwyrm_search_candidates(
            payload=search_request.payload,
            query_title=title,
            query_year=year_hint,
            max_candidates=max(1, max_candidates),
        )
        if not candidates:
            return BucketAddResolution(
                status="no_match",
                reason="no_candidate_match",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=None,
            )

        if not _should_auto_resolve(candidates):
            return BucketAddResolution(
                status="ambiguous",
                reason="ambiguous_match",
                selected_candidate=None,
                candidates=candidates,
                enrichment=None,
                retry_after_seconds=None,
            )

        selected = candidates[0]
        enrichment = _enrichment_from_bookwyrm_search_candidate(
            candidate=selected,
            query_title=title,
            query_year=year_hint,
        )
        return BucketAddResolution(
            status="resolved",
            reason="high_confidence_match",
            selected_candidate=selected,
            candidates=candidates,
            enrichment=enrichment,
            retry_after_seconds=None,
        )

    def _enrich_with_bookwyrm(
        self,
        *,
        title: str,
        year: int | None,
    ) -> BucketEnrichment | None:
        resolution = self.resolve_for_bucket_add(
            title=title,
            domain="book",
            year=year,
            bookwyrm_key=None,
            max_candidates=5,
        )
        if resolution.status != "resolved" or resolution.enrichment is None:
            return None
        return resolution.enrichment

    def _resolve_musicbrainz_for_bucket_add(
        self,
        *,
        title: str,
        year: int | None,
        artist_hint: str | None,
        musicbrainz_release_group_id: str | None,
        max_candidates: int,
    ) -> BucketAddResolution:
        year_hint = year if year is not None else _parse_year(title)
        artist_hint = _normalize_optional_text(artist_hint)
        normalized_id = _normalize_musicbrainz_release_group_id(musicbrainz_release_group_id)
        if normalized_id is not None:
            detail_request = self._fetch_musicbrainz_release_group_details(
                release_group_id=normalized_id
            )
            if detail_request.rate_limited:
                return BucketAddResolution(
                    status="rate_limited",
                    reason="musicbrainz_rate_limited",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=detail_request.retry_after_seconds,
                )
            if detail_request.payload is None:
                return BucketAddResolution(
                    status="no_match",
                    reason="musicbrainz_id_not_found",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=None,
                )

            selected_candidate = _candidate_from_musicbrainz_detail(
                payload=detail_request.payload,
                query_title=title,
                query_year=year_hint,
                query_artist=artist_hint,
                fallback_release_group_id=normalized_id,
            )
            if selected_candidate is None:
                return BucketAddResolution(
                    status="no_match",
                    reason="musicbrainz_not_album",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=None,
                )
            enrichment = _enrichment_from_musicbrainz_payload(
                payload=detail_request.payload,
                query_title=title,
                query_year=year_hint,
                query_artist=artist_hint,
                fallback_release_group_id=normalized_id,
                fallback_artist=None,
            )
            if enrichment is None:
                return BucketAddResolution(
                    status="no_match",
                    reason="musicbrainz_not_album",
                    selected_candidate=None,
                    candidates=[],
                    enrichment=None,
                    retry_after_seconds=None,
                )
            return BucketAddResolution(
                status="resolved",
                reason="resolved_from_musicbrainz_id",
                selected_candidate=selected_candidate,
                candidates=[],
                enrichment=enrichment,
                retry_after_seconds=None,
            )

        search_request = self._search_musicbrainz_release_groups(
            title=title,
            artist_hint=artist_hint,
        )
        if search_request.rate_limited:
            return BucketAddResolution(
                status="rate_limited",
                reason="musicbrainz_rate_limited",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=search_request.retry_after_seconds,
            )
        if search_request.payload is None:
            return BucketAddResolution(
                status="no_match",
                reason="musicbrainz_search_unavailable",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=None,
            )

        candidates = _musicbrainz_search_candidates(
            payload=search_request.payload,
            query_title=title,
            query_year=year_hint,
            query_artist=artist_hint,
            max_candidates=max(1, max_candidates),
        )
        if not candidates:
            return BucketAddResolution(
                status="no_match",
                reason="musicbrainz_no_candidate_match",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=None,
            )

        if not _should_auto_resolve(candidates):
            return BucketAddResolution(
                status="ambiguous",
                reason="ambiguous_match",
                selected_candidate=None,
                candidates=candidates,
                enrichment=None,
                retry_after_seconds=None,
            )

        selected = candidates[0]
        enrichment = _enrichment_from_musicbrainz_search_candidate(
            candidate=selected,
            query_title=title,
            query_year=year_hint,
            query_artist=artist_hint,
        )
        return BucketAddResolution(
            status="resolved",
            reason="high_confidence_match",
            selected_candidate=selected,
            candidates=candidates,
            enrichment=enrichment,
            retry_after_seconds=None,
        )

    def _enrich_with_musicbrainz(
        self,
        *,
        title: str,
        year: int | None,
    ) -> BucketEnrichment | None:
        resolution = self.resolve_for_bucket_add(
            title=title,
            domain="music",
            year=year,
            musicbrainz_release_group_id=None,
            max_candidates=5,
        )
        if resolution.status != "resolved" or resolution.enrichment is None:
            return None
        return resolution.enrichment

    def _search_musicbrainz_release_groups(
        self,
        *,
        title: str,
        artist_hint: str | None,
    ) -> _MusicbrainzRequest:
        query_parts = [f"releasegroup:{_musicbrainz_query_quoted(title)}", "primarytype:album"]
        normalized_artist_hint = _normalize_optional_text(artist_hint)
        if normalized_artist_hint is not None:
            query_parts.insert(1, f"artist:{_musicbrainz_query_quoted(normalized_artist_hint)}")
        query = " AND ".join(query_parts)
        params = {
            "query": query,
            "fmt": "json",
            "limit": "10",
        }
        url = f"{self._musicbrainz_base_url}/ws/2/release-group/?{urlencode(params)}"
        return self._musicbrainz_request_json(url)

    def _fetch_musicbrainz_release_group_details(
        self,
        *,
        release_group_id: str,
    ) -> _MusicbrainzRequest:
        params = {
            "fmt": "json",
            "inc": "artists+genres+tags+ratings",
        }
        url = (
            f"{self._musicbrainz_base_url}/ws/2/release-group/"
            f"{release_group_id}?{urlencode(params)}"
        )
        return self._musicbrainz_request_json(url)

    def _musicbrainz_request_json(self, url: str) -> _MusicbrainzRequest:
        if self._musicbrainz_quota_repository is not None:
            snapshot = self._musicbrainz_quota_repository.try_consume_call(
                daily_soft_limit=self._musicbrainz_daily_soft_limit,
                min_interval_seconds=self._musicbrainz_min_interval_seconds,
            )
            if not snapshot.allowed:
                return _MusicbrainzRequest(
                    payload=None,
                    rate_limited=True,
                    retry_after_seconds=snapshot.retry_after_seconds,
                )

        payload = _fetch_json(
            url,
            timeout_seconds=self._http_timeout_seconds,
            headers={
                "Accept": "application/json",
                "User-Agent": self._musicbrainz_user_agent,
            },
        )
        return _MusicbrainzRequest(payload=payload, rate_limited=False, retry_after_seconds=None)

    def _search_bookwyrm(self, *, title: str) -> _BookwyrmSearchRequest:
        params = {
            "q": title,
            "min_confidence": "0.1",
        }
        url = f"{self._bookwyrm_base_url}/search.json?{urlencode(params)}"
        return self._bookwyrm_request_list(
            url,
            accept_header="application/json",
        )

    def _fetch_bookwyrm_details(self, *, key: str) -> _BookwyrmDetailRequest:
        return self._bookwyrm_request_dict(
            key,
            accept_header="application/activity+json, application/json",
        )

    def _bookwyrm_request_list(self, url: str, *, accept_header: str) -> _BookwyrmSearchRequest:
        if self._bookwyrm_quota_repository is not None:
            snapshot = self._bookwyrm_quota_repository.try_consume_call(
                daily_soft_limit=self._bookwyrm_daily_soft_limit,
                min_interval_seconds=self._bookwyrm_min_interval_seconds,
            )
            if not snapshot.allowed:
                return _BookwyrmSearchRequest(
                    payload=None,
                    rate_limited=True,
                    retry_after_seconds=snapshot.retry_after_seconds,
                )
        payload = _fetch_json_list(
            url,
            timeout_seconds=self._http_timeout_seconds,
            headers={
                "Accept": accept_header,
                "User-Agent": self._bookwyrm_user_agent,
            },
        )
        return _BookwyrmSearchRequest(payload=payload, rate_limited=False, retry_after_seconds=None)

    def _bookwyrm_request_dict(self, url: str, *, accept_header: str) -> _BookwyrmDetailRequest:
        if self._bookwyrm_quota_repository is not None:
            snapshot = self._bookwyrm_quota_repository.try_consume_call(
                daily_soft_limit=self._bookwyrm_daily_soft_limit,
                min_interval_seconds=self._bookwyrm_min_interval_seconds,
            )
            if not snapshot.allowed:
                return _BookwyrmDetailRequest(
                    payload=None,
                    rate_limited=True,
                    retry_after_seconds=snapshot.retry_after_seconds,
                )
        payload = _fetch_json(
            url,
            timeout_seconds=self._http_timeout_seconds,
            headers={
                "Accept": accept_header,
                "User-Agent": self._bookwyrm_user_agent,
            },
        )
        return _BookwyrmDetailRequest(payload=payload, rate_limited=False, retry_after_seconds=None)

    def _search_tmdb(
        self,
        *,
        title: str,
        media_type: Literal["movie", "tv"],
        year: int | None,
    ) -> _TmdbRequest:
        if self._tmdb_api_key is None:
            return _TmdbRequest(payload=None, rate_limited=False, retry_after_seconds=None)
        params: dict[str, str] = {
            "api_key": self._tmdb_api_key,
            "query": title,
            "include_adult": "false",
            "language": "en-US",
        }
        if year is not None:
            if media_type == "movie":
                params["year"] = str(year)
            else:
                params["first_air_date_year"] = str(year)
        url = f"https://api.themoviedb.org/3/search/{media_type}?{urlencode(params)}"
        return self._tmdb_request_json(url)

    def _fetch_tmdb_details(
        self,
        *,
        media_type: Literal["movie", "tv"],
        tmdb_id: int,
    ) -> _TmdbRequest:
        if self._tmdb_api_key is None:
            return _TmdbRequest(payload=None, rate_limited=False, retry_after_seconds=None)
        params = {
            "api_key": self._tmdb_api_key,
            "append_to_response": "external_ids",
            "language": "en-US",
        }
        detail_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?{urlencode(params)}"
        return self._tmdb_request_json(detail_url)

    def _tmdb_request_json(self, url: str) -> _TmdbRequest:
        if self._tmdb_quota_repository is not None:
            snapshot = self._tmdb_quota_repository.try_consume_call(
                daily_soft_limit=self._tmdb_daily_soft_limit,
                min_interval_seconds=self._tmdb_min_interval_seconds,
            )
            if not snapshot.allowed:
                return _TmdbRequest(
                    payload=None,
                    rate_limited=True,
                    retry_after_seconds=snapshot.retry_after_seconds,
                )
        payload = _fetch_json(url, timeout_seconds=self._http_timeout_seconds)
        return _TmdbRequest(payload=payload, rate_limited=False, retry_after_seconds=None)

    def _enrich_with_itunes(
        self,
        *,
        title: str,
        domain: str,
    ) -> BucketEnrichment | None:
        if domain not in {"movie", "tv", "show"}:
            return None

        params = {
            "term": title,
            "entity": "movie" if domain == "movie" else "tvSeason",
            "limit": "5",
        }
        url = f"https://itunes.apple.com/search?{urlencode(params)}"
        payload = _fetch_json(url, timeout_seconds=self._http_timeout_seconds)
        if payload is None:
            return None
        results_raw = payload.get("results")
        if not isinstance(results_raw, list):
            return None

        results = cast(list[object], results_raw)
        best_match = _pick_best_itunes_match(title, results)
        if best_match is None:
            return None

        track_id = _as_str(best_match.get("trackId"))
        track_name = _as_str(best_match.get("trackName"))
        confidence = _title_similarity(title, track_name)
        duration_minutes = _duration_from_millis(best_match.get("trackTimeMillis"))
        primary_genre = _as_str(best_match.get("primaryGenreName"))
        release_date = _as_str(best_match.get("releaseDate"))
        year = _parse_year(release_date)
        external_url = _normalize_optional_text(_as_str(best_match.get("trackViewUrl")))
        short_description = _as_str(best_match.get("shortDescription"))
        long_description = _as_str(best_match.get("longDescription"))

        source_refs: list[dict[str, str]] = []
        if track_id is not None:
            source_refs.append({"type": "external_api", "id": f"itunes:{track_id}"})

        metadata = {
            "track_name": track_name,
            "content_advisory_rating": _as_str(best_match.get("contentAdvisoryRating")),
            "country": _as_str(best_match.get("country")),
            "short_description": short_description,
            "long_description": long_description,
        }

        genres: list[str] = []
        if primary_genre is not None:
            genres.append(primary_genre)

        return BucketEnrichment(
            canonical_id=(f"itunes:{track_id}" if track_id is not None else None),
            year=year,
            duration_minutes=duration_minutes,
            rating=None,
            popularity=None,
            genres=genres,
            tags=[],
            providers=[],
            external_url=external_url,
            confidence=round(confidence, 4),
            metadata=metadata,
            source_refs=source_refs,
            provider="itunes",
        )


def _empty_enrichment() -> BucketEnrichment:
    return BucketEnrichment(
        canonical_id=None,
        year=None,
        duration_minutes=None,
        rating=None,
        popularity=None,
        genres=[],
        tags=[],
        providers=[],
        external_url=None,
        confidence=None,
        metadata={},
        source_refs=[],
        provider=None,
    )


def _fetch_json(
    url: str,
    *,
    timeout_seconds: float,
    headers: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    parsed = _fetch_json_value(url, timeout_seconds=timeout_seconds, headers=headers)
    if not isinstance(parsed, dict):
        return None
    raw_dict = cast(dict[object, object], parsed)
    payload: dict[str, Any] = {}
    for key, value in raw_dict.items():
        if isinstance(key, str):
            payload[key] = value
    return payload


def _fetch_json_list(
    url: str,
    *,
    timeout_seconds: float,
    headers: dict[str, str] | None = None,
) -> list[dict[str, Any]] | None:
    parsed = _fetch_json_value(url, timeout_seconds=timeout_seconds, headers=headers)
    if not isinstance(parsed, list):
        return None
    raw_list = cast(list[object], parsed)
    items: list[dict[str, Any]] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue
        items.append(_normalize_object_dict(cast(dict[object, object], entry)))
    return items


def _fetch_json_value(
    url: str,
    *,
    timeout_seconds: float,
    headers: dict[str, str] | None = None,
) -> object | None:
    request = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError):
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed


def _pick_best_itunes_match(title: str, candidates: list[object]) -> dict[str, Any] | None:
    best_match: dict[str, Any] | None = None
    best_score = -1.0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        raw_candidate = cast(dict[object, object], candidate)
        candidate_title = _as_str(raw_candidate.get("trackName"))
        score = _title_similarity(title, candidate_title)
        if score > best_score:
            best_score = score
            best_match = _normalize_object_dict(raw_candidate)
    if best_score < 0.45:
        return None
    return best_match


def _tmdb_search_candidates(
    *,
    payload: dict[str, Any],
    media_type: Literal["movie", "tv"],
    query_title: str,
    query_year: int | None,
    max_candidates: int,
) -> list[BucketResolveCandidate]:
    results_raw = payload.get("results")
    if not isinstance(results_raw, list):
        return []
    results = cast(list[object], results_raw)
    title_key = "title" if media_type == "movie" else "name"
    date_key = "release_date" if media_type == "movie" else "first_air_date"

    matches: list[BucketResolveCandidate] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        item = cast(dict[object, object], result)
        tmdb_id = _as_int(item.get("id"))
        candidate_title = _as_str(item.get(title_key))
        if tmdb_id is None or candidate_title is None:
            continue

        candidate_year = _parse_year(_as_str(item.get(date_key)))
        confidence = _tmdb_match_confidence(
            query_title=query_title,
            candidate_title=candidate_title,
            query_year=query_year,
            candidate_year=candidate_year,
        )
        if confidence < 0.45:
            continue

        matches.append(
            BucketResolveCandidate(
                canonical_id=f"tmdb:{media_type}:{tmdb_id}",
                provider="tmdb",
                tmdb_id=tmdb_id,
                media_type=media_type,
                title=candidate_title,
                year=candidate_year,
                confidence=round(confidence, 4),
                popularity=_as_float(item.get("popularity")),
                vote_count=_as_int(item.get("vote_count")),
                external_url=f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
            )
        )

    if query_year is not None:
        exact_year_matches = [candidate for candidate in matches if candidate.year == query_year]
        if exact_year_matches:
            matches = exact_year_matches

    matches = _filter_obscure_tmdb_candidates(matches, query_year=query_year)
    matches.sort(
        key=lambda candidate: (
            candidate.confidence,
            _candidate_signal(candidate),
        ),
        reverse=True,
    )
    return matches[:max(1, max_candidates)]


def _candidate_from_tmdb_detail(
    payload: dict[str, Any],
    *,
    media_type: Literal["movie", "tv"],
    query_title: str,
) -> BucketResolveCandidate | None:
    title_key = "title" if media_type == "movie" else "name"
    date_key = "release_date" if media_type == "movie" else "first_air_date"
    tmdb_id = _as_int(payload.get("id"))
    title = _as_str(payload.get(title_key))
    if tmdb_id is None or title is None:
        return None
    year = _parse_year(_as_str(payload.get(date_key)))
    return BucketResolveCandidate(
        canonical_id=f"tmdb:{media_type}:{tmdb_id}",
        provider="tmdb",
        tmdb_id=tmdb_id,
        media_type=media_type,
        title=title,
        year=year,
        confidence=round(_title_similarity(query_title, title), 4),
        popularity=_as_float(payload.get("popularity")),
        vote_count=_as_int(payload.get("vote_count")),
        external_url=f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
    )


def _tmdb_search_item_by_id(
    *,
    payload: dict[str, Any],
    tmdb_id: int,
) -> dict[str, Any] | None:
    results_raw = payload.get("results")
    if not isinstance(results_raw, list):
        return None
    results = cast(list[object], results_raw)
    for result in results:
        if not isinstance(result, dict):
            continue
        item = cast(dict[object, object], result)
        item_id = _as_int(item.get("id"))
        if item_id == tmdb_id:
            return _normalize_object_dict(item)
    return None


def _enrichment_from_tmdb_payload(
    *,
    payload: dict[str, Any],
    media_type: Literal["movie", "tv"],
    query_title: str,
) -> BucketEnrichment | None:
    title_field = "title" if media_type == "movie" else "name"
    title_value = _as_str(payload.get(title_field))
    tmdb_id = _as_int(payload.get("id"))
    if tmdb_id is None:
        return None
    tmdb_year = _parse_year(
        _as_str(
            payload.get("release_date")
            if media_type == "movie"
            else payload.get("first_air_date")
        )
    )
    rating = _as_float(payload.get("vote_average"))
    popularity = _as_float(payload.get("popularity"))
    genres = _tmdb_genres(payload)
    runtime_minutes = _tmdb_runtime_minutes(payload, media_type=media_type)
    imdb_id = _tmdb_imdb_id(payload, media_type=media_type)
    confidence = _title_similarity(query_title, title_value)

    metadata = {
        "overview": _as_str(payload.get("overview")),
        "original_title": _as_str(
            payload.get("original_title") if media_type == "movie" else payload.get("original_name")
        ),
        "title": title_value,
        "language": _as_str(payload.get("original_language")),
        "country_codes": _tmdb_country_codes(payload, media_type=media_type),
        "tmdb_id": tmdb_id,
        "tmdb_media_type": media_type,
    }
    if imdb_id is not None:
        metadata["imdb_id"] = imdb_id

    return BucketEnrichment(
        canonical_id=f"tmdb:{media_type}:{tmdb_id}",
        year=tmdb_year,
        duration_minutes=runtime_minutes,
        rating=rating,
        popularity=popularity,
        genres=genres,
        tags=[],
        providers=[],
        external_url=f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
        confidence=round(confidence, 4),
        metadata=metadata,
        source_refs=[{"type": "external_api", "id": f"tmdb:{media_type}:{tmdb_id}"}],
        provider="tmdb",
    )


def _enrichment_from_tmdb_search_item(
    *,
    payload: dict[str, Any],
    media_type: Literal["movie", "tv"],
    query_title: str,
) -> BucketEnrichment | None:
    title_field = "title" if media_type == "movie" else "name"
    date_field = "release_date" if media_type == "movie" else "first_air_date"
    tmdb_id = _as_int(payload.get("id"))
    if tmdb_id is None:
        return None
    title_value = _as_str(payload.get(title_field))
    year = _parse_year(_as_str(payload.get(date_field)))
    confidence = _title_similarity(query_title, title_value)

    metadata = {
        "overview": _as_str(payload.get("overview")),
        "title": title_value,
        "language": _as_str(payload.get("original_language")),
        "tmdb_id": tmdb_id,
        "tmdb_media_type": media_type,
    }

    return BucketEnrichment(
        canonical_id=f"tmdb:{media_type}:{tmdb_id}",
        year=year,
        duration_minutes=None,
        rating=_as_float(payload.get("vote_average")),
        popularity=_as_float(payload.get("popularity")),
        genres=[],
        tags=[],
        providers=[],
        external_url=f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
        confidence=round(confidence, 4),
        metadata=metadata,
        source_refs=[{"type": "external_api", "id": f"tmdb:{media_type}:{tmdb_id}"}],
        provider="tmdb",
    )


def _bookwyrm_search_candidates(
    *,
    payload: list[dict[str, Any]],
    query_title: str,
    query_year: int | None,
    max_candidates: int,
) -> list[BucketResolveCandidate]:
    matches: list[BucketResolveCandidate] = []
    for item in payload:
        key = _normalize_bookwyrm_key(_as_str(item.get("key")))
        title = _as_str(item.get("title"))
        if key is None or title is None:
            continue
        candidate_year = _as_int(item.get("year"))
        confidence = _bookwyrm_match_confidence(
            query_title=query_title,
            candidate_title=title,
            query_year=query_year,
            candidate_year=candidate_year,
            provider_confidence=_as_float(item.get("confidence")),
        )
        if confidence < 0.5:
            continue
        matches.append(
            BucketResolveCandidate(
                canonical_id=f"bookwyrm:{key}",
                provider="bookwyrm",
                title=title,
                year=candidate_year,
                confidence=round(confidence, 4),
                external_url=key,
                media_type="book",
                bookwyrm_key=key,
                author=_as_str(item.get("author")),
            )
        )
    matches = _collapse_duplicate_bookwyrm_candidates(matches)
    matches.sort(
        key=lambda candidate: (
            candidate.confidence,
            candidate.year or 0,
        ),
        reverse=True,
    )
    return matches[: max(1, max_candidates)]


def _collapse_duplicate_bookwyrm_candidates(
    candidates: list[BucketResolveCandidate],
) -> list[BucketResolveCandidate]:
    if len(candidates) <= 1:
        return candidates

    # BookWyrm often returns multiple editions for the same work where one
    # entry has year/metadata and another is sparse. Collapse strict duplicates.
    grouped: dict[tuple[str, str, str], list[BucketResolveCandidate]] = {}
    by_title_author_known_year: set[tuple[str, str]] = set()
    for candidate in candidates:
        normalized_title = _normalize_match_text(candidate.title)
        normalized_author = _normalize_match_text(candidate.author)
        year_key = str(candidate.year) if candidate.year is not None else "-"
        if candidate.year is not None:
            by_title_author_known_year.add((normalized_title, normalized_author))
        grouped.setdefault((normalized_title, normalized_author, year_key), []).append(candidate)

    collapsed: list[BucketResolveCandidate] = []
    for (normalized_title, normalized_author, year_key), group in grouped.items():
        if (
            year_key == "-"
            and (normalized_title, normalized_author) in by_title_author_known_year
        ):
            # Prefer dated entries when the same title/author exists with known year.
            continue
        collapsed.append(_best_bookwyrm_candidate(group))
    return collapsed


def _best_bookwyrm_candidate(candidates: list[BucketResolveCandidate]) -> BucketResolveCandidate:
    if len(candidates) == 1:
        return candidates[0]

    def _candidate_rank(candidate: BucketResolveCandidate) -> tuple[float, int, int, int]:
        has_year = 1 if candidate.year is not None else 0
        has_author = 1 if _normalize_optional_text(candidate.author) is not None else 0
        numeric_id = _bookwyrm_numeric_id(candidate.bookwyrm_key)
        id_tiebreak = -(numeric_id if numeric_id is not None else 1_000_000_000)
        return (candidate.confidence, has_year, has_author, id_tiebreak)

    return max(candidates, key=_candidate_rank)


def _candidate_from_bookwyrm_detail(
    *,
    payload: dict[str, Any],
    query_title: str,
    query_year: int | None,
    fallback_key: str,
) -> BucketResolveCandidate | None:
    key = _normalize_bookwyrm_key(_as_str(payload.get("id"))) or fallback_key
    title = _as_str(payload.get("title"))
    if title is None:
        return None
    year = _parse_year(
        _as_str(payload.get("publishedDate")) or _as_str(payload.get("firstPublishedDate"))
    )
    confidence = _bookwyrm_match_confidence(
        query_title=query_title,
        candidate_title=title,
        query_year=query_year,
        candidate_year=year,
        provider_confidence=None,
    )
    return BucketResolveCandidate(
        canonical_id=f"bookwyrm:{key}",
        provider="bookwyrm",
        title=title,
        year=year,
        confidence=round(confidence, 4),
        external_url=key,
        media_type="book",
        bookwyrm_key=key,
    )


def _enrichment_from_bookwyrm_payload(
    *,
    payload: dict[str, Any],
    query_title: str,
    query_year: int | None,
    fallback_key: str,
    fallback_author: str | None,
) -> BucketEnrichment | None:
    key = _normalize_bookwyrm_key(_as_str(payload.get("id"))) or fallback_key
    title = _as_str(payload.get("title"))
    confidence_title = title or query_title
    year = _parse_year(
        _as_str(payload.get("publishedDate")) or _as_str(payload.get("firstPublishedDate"))
    )
    confidence = _bookwyrm_match_confidence(
        query_title=query_title,
        candidate_title=confidence_title,
        query_year=query_year,
        candidate_year=year,
        provider_confidence=None,
    )
    author = fallback_author
    authors_raw = payload.get("authors")
    if isinstance(authors_raw, list):
        authors = cast(list[object], authors_raw)
        if authors:
            first_author = _as_str(authors[0])
            if first_author is not None:
                author = first_author

    subjects = _as_str_list(payload.get("subjects"))
    metadata: dict[str, Any] = {
        "title": title,
        "author": author,
        "description": _bookwyrm_description_text(payload.get("description")),
        "languages": _as_str_list(payload.get("languages")),
        "subjects": subjects,
        "bookwyrm_key": key,
        "bookwyrm_type": _as_str(payload.get("type")),
        "bookwyrm_openlibrary_key": _as_str(payload.get("openlibraryKey")),
        "isbn10": _as_str(payload.get("isbn10")),
        "isbn13": _as_str(payload.get("isbn13")),
    }
    cover_raw = payload.get("cover")
    if isinstance(cover_raw, dict):
        cover = cast(dict[object, object], cover_raw)
        cover_url = _as_str(cover.get("url"))
        if cover_url is not None:
            metadata["cover_url"] = cover_url

    return BucketEnrichment(
        canonical_id=f"bookwyrm:{key}",
        year=year,
        duration_minutes=None,
        rating=None,
        popularity=None,
        genres=[],
        tags=subjects,
        providers=[],
        external_url=key,
        confidence=round(confidence, 4),
        metadata=metadata,
        source_refs=[{"type": "external_api", "id": f"bookwyrm:{key}"}],
        provider="bookwyrm",
    )


def _enrichment_from_bookwyrm_search_candidate(
    *,
    candidate: BucketResolveCandidate,
    query_title: str,
    query_year: int | None,
) -> BucketEnrichment:
    year = candidate.year
    confidence = _bookwyrm_match_confidence(
        query_title=query_title,
        candidate_title=candidate.title,
        query_year=query_year,
        candidate_year=year,
        provider_confidence=candidate.confidence,
    )
    metadata = {
        "title": candidate.title,
        "author": candidate.author,
        "bookwyrm_key": candidate.bookwyrm_key,
    }
    return BucketEnrichment(
        canonical_id=candidate.canonical_id,
        year=year,
        duration_minutes=None,
        rating=None,
        popularity=None,
        genres=[],
        tags=[],
        providers=[],
        external_url=candidate.external_url,
        confidence=round(confidence, 4),
        metadata=metadata,
        source_refs=[{"type": "external_api", "id": candidate.canonical_id}],
        provider="bookwyrm",
    )


def _musicbrainz_search_candidates(
    *,
    payload: dict[str, Any],
    query_title: str,
    query_year: int | None,
    query_artist: str | None,
    max_candidates: int,
) -> list[BucketResolveCandidate]:
    results_raw = payload.get("release-groups")
    if not isinstance(results_raw, list):
        return []
    results = cast(list[object], results_raw)

    matches: list[BucketResolveCandidate] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        item = cast(dict[object, object], result)
        release_group_id = _normalize_musicbrainz_release_group_id(_as_str(item.get("id")))
        title = _as_str(item.get("title"))
        if release_group_id is None or title is None:
            continue
        primary_type = _normalize_optional_text(_as_str(item.get("primary-type")))
        if primary_type is None or primary_type.lower() != "album":
            continue

        year = _parse_year(_as_str(item.get("first-release-date")))
        artist = _musicbrainz_artist_credit(item.get("artist-credit"))
        provider_score = _as_int(item.get("score"))
        release_count = _as_int(item.get("release-count")) or _as_int(item.get("count"))
        confidence = _musicbrainz_match_confidence(
            query_title=query_title,
            candidate_title=title,
            query_year=query_year,
            candidate_year=year,
            provider_score=provider_score,
            query_artist=query_artist,
            candidate_artist=artist,
        )
        if confidence < 0.5:
            continue

        matches.append(
            BucketResolveCandidate(
                canonical_id=f"musicbrainz:release-group:{release_group_id}",
                provider="musicbrainz",
                title=title,
                year=year,
                confidence=round(confidence, 4),
                external_url=_musicbrainz_release_group_url(release_group_id),
                media_type="music",
                popularity=(float(provider_score) if provider_score is not None else None),
                vote_count=release_count,
                musicbrainz_release_group_id=release_group_id,
                artist=artist,
            )
        )

    matches = _collapse_duplicate_musicbrainz_candidates(matches)
    matches = _filter_obscure_musicbrainz_candidates(
        matches,
        query_year=query_year,
        query_artist=query_artist,
    )
    matches.sort(
        key=lambda candidate: (
            candidate.confidence,
            _candidate_signal(candidate),
            candidate.year or 0,
        ),
        reverse=True,
    )
    return matches[: max(1, max_candidates)]


def _collapse_duplicate_musicbrainz_candidates(
    candidates: list[BucketResolveCandidate],
) -> list[BucketResolveCandidate]:
    if len(candidates) <= 1:
        return candidates

    grouped: dict[tuple[str, str, str], list[BucketResolveCandidate]] = {}
    by_title_artist_known_year: set[tuple[str, str]] = set()
    for candidate in candidates:
        normalized_title = _normalize_match_text(candidate.title)
        normalized_artist = _normalize_match_text(candidate.artist)
        year_key = str(candidate.year) if candidate.year is not None else "-"
        if candidate.year is not None:
            by_title_artist_known_year.add((normalized_title, normalized_artist))
        grouped.setdefault((normalized_title, normalized_artist, year_key), []).append(candidate)

    collapsed: list[BucketResolveCandidate] = []
    for (normalized_title, normalized_artist, year_key), group in grouped.items():
        if (
            year_key == "-"
            and (normalized_title, normalized_artist) in by_title_artist_known_year
        ):
            continue
        collapsed.append(_best_musicbrainz_candidate(group))
    return collapsed


def _best_musicbrainz_candidate(candidates: list[BucketResolveCandidate]) -> BucketResolveCandidate:
    if len(candidates) == 1:
        return candidates[0]

    def _rank(candidate: BucketResolveCandidate) -> tuple[float, int, int]:
        has_year = 1 if candidate.year is not None else 0
        stable = _musicbrainz_stable_rank(candidate.musicbrainz_release_group_id)
        return (candidate.confidence, has_year, stable)

    return max(candidates, key=_rank)


def _candidate_from_musicbrainz_detail(
    *,
    payload: dict[str, Any],
    query_title: str,
    query_year: int | None,
    query_artist: str | None,
    fallback_release_group_id: str,
) -> BucketResolveCandidate | None:
    release_group_id = _normalize_musicbrainz_release_group_id(_as_str(payload.get("id")))
    if release_group_id is None:
        release_group_id = fallback_release_group_id
    title = _as_str(payload.get("title"))
    if title is None:
        return None
    primary_type = _normalize_optional_text(_as_str(payload.get("primary-type")))
    if primary_type is None or primary_type.lower() != "album":
        return None
    year = _parse_year(_as_str(payload.get("first-release-date")))
    artist = _musicbrainz_artist_credit(payload.get("artist-credit"))
    confidence = _musicbrainz_match_confidence(
        query_title=query_title,
        candidate_title=title,
        query_year=query_year,
        candidate_year=year,
        provider_score=None,
        query_artist=query_artist,
        candidate_artist=artist,
    )
    return BucketResolveCandidate(
        canonical_id=f"musicbrainz:release-group:{release_group_id}",
        provider="musicbrainz",
        title=title,
        year=year,
        confidence=round(confidence, 4),
        external_url=_musicbrainz_release_group_url(release_group_id),
        media_type="music",
        musicbrainz_release_group_id=release_group_id,
        artist=artist,
        vote_count=_musicbrainz_votes_count(payload.get("rating")),
    )


def _enrichment_from_musicbrainz_payload(
    *,
    payload: dict[str, Any],
    query_title: str,
    query_year: int | None,
    query_artist: str | None,
    fallback_release_group_id: str,
    fallback_artist: str | None,
) -> BucketEnrichment | None:
    release_group_id = _normalize_musicbrainz_release_group_id(_as_str(payload.get("id")))
    if release_group_id is None:
        release_group_id = fallback_release_group_id
    title = _as_str(payload.get("title"))
    if title is None:
        return None
    primary_type = _normalize_optional_text(_as_str(payload.get("primary-type")))
    if primary_type is None or primary_type.lower() != "album":
        return None
    year = _parse_year(_as_str(payload.get("first-release-date")))
    artist = _musicbrainz_artist_credit(payload.get("artist-credit")) or fallback_artist
    confidence = _musicbrainz_match_confidence(
        query_title=query_title,
        candidate_title=title,
        query_year=query_year,
        candidate_year=year,
        provider_score=None,
        query_artist=query_artist,
        candidate_artist=artist,
    )
    rating = _musicbrainz_rating_value(payload.get("rating"))
    votes_count = _musicbrainz_votes_count(payload.get("rating"))
    release_count = _as_int(payload.get("release-count"))

    genres = _musicbrainz_genres(payload.get("genres"))
    tags = _musicbrainz_tags(payload.get("tags"))
    secondary_types = _as_str_list(payload.get("secondary-types"))
    metadata = {
        "title": title,
        "artist": artist,
        "musicbrainz_release_group_id": release_group_id,
        "musicbrainz_primary_type": primary_type,
        "musicbrainz_secondary_types": secondary_types,
        "musicbrainz_release_count": release_count,
        "musicbrainz_rating_votes_count": votes_count,
    }

    return BucketEnrichment(
        canonical_id=f"musicbrainz:release-group:{release_group_id}",
        year=year,
        duration_minutes=None,
        rating=rating,
        popularity=(
            float(release_count)
            if release_count is not None
            else (float(votes_count) if votes_count is not None else None)
        ),
        genres=genres,
        tags=tags,
        providers=[],
        external_url=_musicbrainz_release_group_url(release_group_id),
        confidence=round(confidence, 4),
        metadata=metadata,
        source_refs=[
            {"type": "external_api", "id": f"musicbrainz:release-group:{release_group_id}"}
        ],
        provider="musicbrainz",
    )


def _enrichment_from_musicbrainz_search_candidate(
    *,
    candidate: BucketResolveCandidate,
    query_title: str,
    query_year: int | None,
    query_artist: str | None,
) -> BucketEnrichment:
    confidence = _musicbrainz_match_confidence(
        query_title=query_title,
        candidate_title=candidate.title,
        query_year=query_year,
        candidate_year=candidate.year,
        provider_score=round(candidate.confidence * 100),
        query_artist=query_artist,
        candidate_artist=candidate.artist,
    )
    metadata = {
        "title": candidate.title,
        "artist": candidate.artist,
        "musicbrainz_release_group_id": candidate.musicbrainz_release_group_id,
        "musicbrainz_primary_type": "Album",
    }
    return BucketEnrichment(
        canonical_id=candidate.canonical_id,
        year=candidate.year,
        duration_minutes=None,
        rating=None,
        popularity=None,
        genres=[],
        tags=[],
        providers=[],
        external_url=candidate.external_url,
        confidence=round(confidence, 4),
        metadata=metadata,
        source_refs=[{"type": "external_api", "id": candidate.canonical_id}],
        provider="musicbrainz",
    )


def _should_auto_resolve(candidates: list[BucketResolveCandidate]) -> bool:
    if not candidates:
        return False
    best = candidates[0]
    if best.confidence < 0.86:
        return False
    if len(candidates) == 1:
        return True
    second = candidates[1]
    if (best.confidence - second.confidence) >= 0.12:
        return True

    best_signal = _candidate_signal(best)
    second_signal = _candidate_signal(second)
    if best_signal <= 0 and second_signal <= 0:
        return False
    return best.confidence >= 0.9 and best_signal >= (second_signal * 2.8)


def _filter_obscure_tmdb_candidates(
    candidates: list[BucketResolveCandidate],
    *,
    query_year: int | None,
) -> list[BucketResolveCandidate]:
    if query_year is not None:
        return candidates

    filtered = [candidate for candidate in candidates if _candidate_has_discovery_signal(candidate)]
    if filtered:
        return filtered
    return candidates


def _filter_obscure_musicbrainz_candidates(
    candidates: list[BucketResolveCandidate],
    *,
    query_year: int | None,
    query_artist: str | None,
) -> list[BucketResolveCandidate]:
    if query_year is not None or _normalize_optional_text(query_artist) is not None:
        return candidates

    filtered = [
        candidate
        for candidate in candidates
        if (
            (candidate.popularity is not None and candidate.popularity >= 70.0)
            or (candidate.vote_count is not None and candidate.vote_count >= 2)
        )
    ]
    if filtered:
        return filtered
    return candidates


def _candidate_has_discovery_signal(candidate: BucketResolveCandidate) -> bool:
    popularity = candidate.popularity if candidate.popularity is not None else 0.0
    vote_count = candidate.vote_count if candidate.vote_count is not None else 0
    return popularity >= 8.0 or vote_count >= 80


def _candidate_signal(candidate: BucketResolveCandidate) -> float:
    popularity = candidate.popularity if candidate.popularity is not None else 0.0
    vote_count = candidate.vote_count if candidate.vote_count is not None else 0
    return popularity + min(5000, vote_count) / 25.0


def _tmdb_match_confidence(
    *,
    query_title: str,
    candidate_title: str,
    query_year: int | None,
    candidate_year: int | None,
) -> float:
    score = _title_similarity(query_title, candidate_title)
    if query_year is None or candidate_year is None:
        return min(1.0, max(0.0, score))
    if query_year == candidate_year:
        score += 0.08
    elif abs(query_year - candidate_year) == 1:
        score += 0.03
    else:
        score -= 0.08
    return min(1.0, max(0.0, score))


def _tmdb_media_type_for_domain(domain: str) -> Literal["movie", "tv"] | None:
    normalized = domain.strip().lower()
    if normalized == "movie":
        return "movie"
    if normalized in {"tv", "show"}:
        return "tv"
    return None


def _tmdb_genres(payload: dict[str, Any]) -> list[str]:
    genres_raw = payload.get("genres")
    if not isinstance(genres_raw, list):
        return []
    genres_entries = cast(list[object], genres_raw)
    genres: list[str] = []
    seen: set[str] = set()
    for entry in genres_entries:
        if not isinstance(entry, dict):
            continue
        entry_dict = cast(dict[object, object], entry)
        genre_name = _as_str(entry_dict.get("name"))
        if genre_name is None:
            continue
        normalized = genre_name.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        genres.append(genre_name)
    return genres


def _tmdb_runtime_minutes(payload: dict[str, Any], *, media_type: str) -> int | None:
    if media_type == "movie":
        return _as_int(payload.get("runtime"))

    episode_run_time_raw = payload.get("episode_run_time")
    if not isinstance(episode_run_time_raw, list):
        return None
    episode_minutes = cast(list[object], episode_run_time_raw)
    for value in episode_minutes:
        minutes = _as_int(value)
        if minutes is not None and minutes > 0:
            return minutes
    return None


def _tmdb_imdb_id(payload: dict[str, Any], *, media_type: str) -> str | None:
    if media_type == "movie":
        return _normalize_optional_text(_as_str(payload.get("imdb_id")))

    external_ids_raw = payload.get("external_ids")
    if not isinstance(external_ids_raw, dict):
        return None
    external_ids = cast(dict[object, object], external_ids_raw)
    return _normalize_optional_text(_as_str(external_ids.get("imdb_id")))


def _tmdb_country_codes(payload: dict[str, Any], *, media_type: str) -> list[str]:
    if media_type == "movie":
        countries_raw = payload.get("production_countries")
        if not isinstance(countries_raw, list):
            return []
        countries = cast(list[object], countries_raw)
        output: list[str] = []
        seen: set[str] = set()
        for entry in countries:
            if not isinstance(entry, dict):
                continue
            entry_dict = cast(dict[object, object], entry)
            code = _normalize_optional_text(_as_str(entry_dict.get("iso_3166_1")))
            if code is None:
                continue
            normalized = code.upper()
            if normalized in seen:
                continue
            seen.add(normalized)
            output.append(normalized)
        return output

    origin_country_raw = payload.get("origin_country")
    if not isinstance(origin_country_raw, list):
        return []
    origin_countries = cast(list[object], origin_country_raw)
    output: list[str] = []
    seen: set[str] = set()
    for value in origin_countries:
        code = _normalize_optional_text(_as_str(value))
        if code is None:
            continue
        normalized = code.upper()
        if normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _normalize_object_dict(raw: dict[object, object]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(key, str):
            normalized[key] = value
    return normalized


def _title_similarity(expected: str, candidate: str | None) -> float:
    if candidate is None:
        return 0.0
    return SequenceMatcher(None, expected.lower().strip(), candidate.lower().strip()).ratio()


def _duration_from_millis(value: object) -> int | None:
    if isinstance(value, int):
        if value <= 0:
            return None
        return max(1, round(value / 60000))
    if isinstance(value, float):
        if value <= 0:
            return None
        return max(1, round(value / 60000))
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _as_float(value: object) -> float | None:
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    raw_items = cast(list[object], value)
    output: list[str] = []
    seen: set[str] = set()
    for entry in raw_items:
        normalized = _normalize_optional_text(_as_str(entry))
        if normalized is None:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


def _parse_year(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"(19|20)\d{2}", value)
    if match is None:
        return None
    return int(match.group(0))


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _bookwyrm_description_text(value: object) -> str | None:
    if isinstance(value, str):
        return _normalize_optional_text(value)
    if isinstance(value, dict):
        raw_dict = cast(dict[object, object], value)
        if "content" in raw_dict:
            return _normalize_optional_text(_as_str(raw_dict.get("content")))
        if "summary" in raw_dict:
            return _normalize_optional_text(_as_str(raw_dict.get("summary")))
    return None


def _bookwyrm_match_confidence(
    *,
    query_title: str,
    candidate_title: str,
    query_year: int | None,
    candidate_year: int | None,
    provider_confidence: float | None,
) -> float:
    score = _title_similarity(query_title, candidate_title)
    if provider_confidence is not None:
        bounded_provider = min(1.0, max(0.0, provider_confidence))
        score = (score * 0.85) + (bounded_provider * 0.15)
    if query_year is None or candidate_year is None:
        return min(1.0, max(0.0, score))
    if query_year == candidate_year:
        score += 0.06
    elif abs(query_year - candidate_year) == 1:
        score += 0.02
    else:
        score -= 0.05
    return min(1.0, max(0.0, score))


def _normalize_match_text(value: str | None) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return ""
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return normalized.strip()


def _normalize_bookwyrm_key(value: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    if not normalized.startswith(("http://", "https://")):
        return None
    return normalized.rstrip("/")


def _bookwyrm_numeric_id(value: str | None) -> int | None:
    normalized = _normalize_bookwyrm_key(value)
    if normalized is None:
        return None
    match = re.search(r"/book/(\d+)$", normalized)
    if match is None:
        return None
    return int(match.group(1))


def _normalize_musicbrainz_release_group_id(value: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None

    candidate = normalized.rstrip("/")
    if candidate.lower().startswith("musicbrainz:release-group:"):
        candidate = candidate[len("musicbrainz:release-group:") :]
    elif candidate.startswith(("http://", "https://")):
        parsed = urlparse(candidate)
        path = parsed.path.rstrip("/")
        match = re.search(r"/release-group/([0-9a-fA-F-]+)$", path)
        if match is None:
            return None
        candidate = match.group(1)

    lowered = candidate.strip().lower()
    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        lowered,
    ) is None:
        return None
    return lowered


def _musicbrainz_release_group_url(release_group_id: str) -> str:
    return f"https://musicbrainz.org/release-group/{release_group_id}"


def _musicbrainz_artist_credit(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    entries = cast(list[object], value)
    if not entries:
        return None

    parts: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            raw = entry.strip()
            if raw:
                parts.append(raw)
            continue
        if not isinstance(entry, dict):
            continue
        item = cast(dict[object, object], entry)
        name = _as_str(item.get("name"))
        artist_raw = item.get("artist")
        if name is None and isinstance(artist_raw, dict):
            artist_item = cast(dict[object, object], artist_raw)
            name = _as_str(artist_item.get("name"))
        join_phrase = _as_str(item.get("joinphrase"))
        if name is not None:
            parts.append(name)
        if join_phrase is not None:
            parts.append(join_phrase)

    joined = "".join(parts).strip()
    return _normalize_optional_text(joined)


def _musicbrainz_match_confidence(
    *,
    query_title: str,
    candidate_title: str,
    query_year: int | None,
    candidate_year: int | None,
    provider_score: int | None,
    query_artist: str | None,
    candidate_artist: str | None,
) -> float:
    score = _title_similarity(query_title, candidate_title)
    if provider_score is not None:
        bounded_provider = min(100.0, max(0.0, float(provider_score))) / 100.0
        score = (score * 0.75) + (bounded_provider * 0.25)

    artist_similarity = _musicbrainz_artist_similarity(query_artist, candidate_artist)
    if artist_similarity is not None:
        if artist_similarity >= 0.92:
            score += 0.24
        elif artist_similarity >= 0.75:
            score += 0.14
        elif artist_similarity >= 0.6:
            score += 0.05
        else:
            score -= 0.18

    if query_year is None or candidate_year is None:
        return min(1.0, max(0.0, score))
    if query_year == candidate_year:
        score += 0.06
    elif abs(query_year - candidate_year) == 1:
        score += 0.02
    else:
        score -= 0.05
    return min(1.0, max(0.0, score))


def _musicbrainz_artist_similarity(
    query_artist: str | None,
    candidate_artist: str | None,
) -> float | None:
    normalized_query = _normalize_match_text(query_artist)
    normalized_candidate = _normalize_match_text(candidate_artist)
    if not normalized_query or not normalized_candidate:
        return None
    if normalized_query == normalized_candidate:
        return 1.0
    if normalized_query in normalized_candidate or normalized_candidate in normalized_query:
        return 0.95
    return SequenceMatcher(None, normalized_query, normalized_candidate).ratio()


def _musicbrainz_query_quoted(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').strip()
    return f'"{escaped}"'


def _musicbrainz_rating_value(value: object) -> float | None:
    if not isinstance(value, dict):
        return None
    rating = cast(dict[object, object], value)
    return _as_float(rating.get("value"))


def _musicbrainz_votes_count(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    rating = cast(dict[object, object], value)
    return _as_int(rating.get("votes-count"))


def _musicbrainz_genres(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    entries = cast(list[object], value)
    weighted: list[tuple[str, int]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        genre = cast(dict[object, object], entry)
        name = _normalize_optional_text(_as_str(genre.get("name")))
        if name is None:
            continue
        weighted.append((name, _as_int(genre.get("count")) or 0))
    weighted.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return _dedupe_texts([name for name, _ in weighted])


def _musicbrainz_tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    entries = cast(list[object], value)
    weighted: list[tuple[str, int]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tag = cast(dict[object, object], entry)
        name = _normalize_optional_text(_as_str(tag.get("name")))
        if name is None:
            continue
        weighted.append((name, _as_int(tag.get("count")) or 0))
    weighted.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return _dedupe_texts([name for name, _ in weighted])


def _dedupe_texts(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.lower().strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(value)
    return output


def _musicbrainz_stable_rank(release_group_id: str | None) -> int:
    normalized = _normalize_musicbrainz_release_group_id(release_group_id)
    if normalized is None:
        return 0
    try:
        return int(normalized.replace("-", "")[-12:], 16)
    except ValueError:
        return 0


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _normalize_base_url(value: str, *, fallback: str) -> str:
    normalized = _normalize_optional_text(value) or fallback
    return normalized.rstrip("/")
