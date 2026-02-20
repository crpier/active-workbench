from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


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


class BucketMetadataService:
    def __init__(
        self,
        *,
        enrichment_enabled: bool,
        http_timeout_seconds: float,
        omdb_api_key: str | None,
    ) -> None:
        self._enrichment_enabled = enrichment_enabled
        self._http_timeout_seconds = max(0.5, http_timeout_seconds)
        self._omdb_api_key = _normalize_optional_text(omdb_api_key)

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

        if self._omdb_api_key is not None:
            enriched_omdb = self._enrich_with_omdb(title=title, domain=normalized_domain, year=year)
            if enriched_omdb is not None:
                return enriched_omdb

        enriched_itunes = self._enrich_with_itunes(title=title, domain=normalized_domain)
        if enriched_itunes is not None:
            return enriched_itunes

        return _empty_enrichment()

    def _enrich_with_omdb(
        self,
        *,
        title: str,
        domain: str,
        year: int | None,
    ) -> BucketEnrichment | None:
        if self._omdb_api_key is None:
            return None

        params: dict[str, str] = {"apikey": self._omdb_api_key, "t": title}
        if domain in {"movie", "tv"}:
            params["type"] = domain
        if year is not None:
            params["y"] = str(year)

        url = f"https://www.omdbapi.com/?{urlencode(params)}"
        payload = _fetch_json(url, timeout_seconds=self._http_timeout_seconds)
        if payload is None:
            return None
        if str(payload.get("Response", "")).lower() != "true":
            return None

        imdb_id = _normalize_optional_text(_as_str(payload.get("imdbID")))
        runtime_minutes = _parse_runtime_minutes(_as_str(payload.get("Runtime")))
        genres = _split_csv(_as_str(payload.get("Genre")))
        omdb_year = _parse_year(_as_str(payload.get("Year")))
        rating = _safe_float(_as_str(payload.get("imdbRating")))
        popularity = _parse_vote_count(_as_str(payload.get("imdbVotes")))
        metadata = {
            "plot": _as_str(payload.get("Plot")),
            "language": _as_str(payload.get("Language")),
            "country": _as_str(payload.get("Country")),
            "awards": _as_str(payload.get("Awards")),
            "ratings": payload.get("Ratings"),
        }
        source_refs: list[dict[str, str]] = []
        if imdb_id is not None:
            source_refs.append({"type": "external_api", "id": f"omdb:{imdb_id}"})

        return BucketEnrichment(
            canonical_id=imdb_id,
            year=omdb_year,
            duration_minutes=runtime_minutes,
            rating=rating,
            popularity=float(popularity) if popularity is not None else None,
            genres=genres,
            tags=[],
            providers=[],
            external_url=(
                f"https://www.imdb.com/title/{imdb_id}/" if imdb_id is not None else None
            ),
            confidence=0.95,
            metadata=metadata,
            source_refs=source_refs,
            provider="omdb",
        )

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


def _parse_runtime_minutes(runtime: str | None) -> int | None:
    if runtime is None:
        return None
    lowered = runtime.lower()
    minute_match = re.search(r"(\d+)\s*min", lowered)
    if minute_match is not None:
        return int(minute_match.group(1))
    hour_match = re.search(r"(\d+)\s*h", lowered)
    if hour_match is not None:
        return int(hour_match.group(1)) * 60
    return None


def _parse_year(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"(19|20)\d{2}", value)
    if match is None:
        return None
    return int(match.group(0))


def _parse_vote_count(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned.isdigit():
        return None
    return int(cleaned)


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    if value.strip().lower() == "n/a":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    deduped: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        normalized = part.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


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
