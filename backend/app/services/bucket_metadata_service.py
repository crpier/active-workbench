from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

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
    tmdb_id: int
    media_type: Literal["movie", "tv"]
    title: str
    year: int | None
    confidence: float
    popularity: float | None
    vote_count: int | None
    external_url: str


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
    ) -> None:
        self._enrichment_enabled = enrichment_enabled
        self._http_timeout_seconds = max(0.5, http_timeout_seconds)
        self._tmdb_api_key = _normalize_optional_text(tmdb_api_key)
        self._tmdb_quota_repository = tmdb_quota_repository
        self._tmdb_daily_soft_limit = max(0, tmdb_daily_soft_limit)
        self._tmdb_min_interval_seconds = max(0.0, tmdb_min_interval_seconds)

    def resolve_for_bucket_add(
        self,
        *,
        title: str,
        domain: str,
        year: int | None,
        tmdb_id: int | None = None,
        max_candidates: int = 5,
    ) -> BucketAddResolution:
        year_hint = year if year is not None else _parse_year(title)
        normalized_domain = domain.strip().lower()
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
        if not self._enrichment_enabled:
            return BucketAddResolution(
                status="skipped",
                reason="enrichment_disabled",
                selected_candidate=None,
                candidates=[],
                enrichment=None,
                retry_after_seconds=None,
            )
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
        search_item = _tmdb_search_item_by_id(
            payload=search_request.payload,
            tmdb_id=selected.tmdb_id,
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
            media_type=selected.media_type,
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


def _fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any] | None:
    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError):
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    raw_dict = cast(dict[object, object], parsed)
    payload: dict[str, Any] = {}
    for key, value in raw_dict.items():
        if isinstance(key, str):
            payload[key] = value
    return payload


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


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped
