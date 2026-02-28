from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection, Row
from typing import Any, cast
from uuid import uuid4

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database

ACTIVE_STATUS = "active"
COMPLETED_STATUS = "completed"


@dataclass(frozen=True)
class BucketItem:
    item_id: str
    title: str
    normalized_title: str
    domain: str
    status: str
    canonical_id: str | None
    metadata: dict[str, Any]
    source_refs: list[dict[str, str]]
    added_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    last_recommended_at: datetime | None

    @property
    def notes(self) -> str:
        value = self.metadata.get("notes")
        if isinstance(value, str):
            return value
        return ""

    @property
    def year(self) -> int | None:
        return _int_from_metadata(self.metadata.get("year"))

    @property
    def duration_minutes(self) -> int | None:
        return _int_from_metadata(self.metadata.get("duration_minutes"))

    @property
    def rating(self) -> float | None:
        return _float_from_metadata(self.metadata.get("rating"))

    @property
    def popularity(self) -> float | None:
        return _float_from_metadata(self.metadata.get("popularity"))

    @property
    def genres(self) -> list[str]:
        return _str_list_from_metadata(self.metadata.get("genres"))

    @property
    def tags(self) -> list[str]:
        return _str_list_from_metadata(self.metadata.get("tags"))

    @property
    def providers(self) -> list[str]:
        return _str_list_from_metadata(self.metadata.get("providers"))

    @property
    def external_url(self) -> str | None:
        return _text_or_none(self.metadata.get("external_url"))

    @property
    def confidence(self) -> float | None:
        return _float_from_metadata(self.metadata.get("confidence"))

    @property
    def annotation_status(self) -> str:
        return _annotation_status(self.metadata, canonical_id=self.canonical_id)

    @property
    def is_annotated(self) -> bool:
        return self.annotation_status == "annotated"

    @property
    def annotation_provider(self) -> str | None:
        return _text_or_none(self.metadata.get("annotation_provider"))

    @property
    def annotation_last_attempt_at(self) -> str | None:
        return _text_or_none(self.metadata.get("annotation_last_attempt_at"))


class BucketRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create_or_merge_item(
        self,
        *,
        title: str,
        domain: str,
        notes: str,
        year: int | None,
        duration_minutes: int | None,
        rating: float | None,
        popularity: float | None,
        genres: list[str],
        tags: list[str],
        providers: list[str],
        metadata: dict[str, Any],
        source_refs: list[dict[str, str]],
        canonical_id: str | None,
        external_url: str | None,
        confidence: float | None,
    ) -> tuple[BucketItem, str]:
        normalized_domain = _normalize_domain(domain)
        normalized_title = _normalize_title(title)
        normalized_canonical_id = _normalize_optional_text(canonical_id)

        incoming_metadata = _merge_item_metadata(
            base={},
            notes=notes,
            year=year,
            duration_minutes=duration_minutes,
            rating=rating,
            popularity=popularity,
            genres=genres,
            tags=tags,
            providers=providers,
            external_url=external_url,
            confidence=confidence,
            metadata=metadata,
        )
        incoming_metadata = _normalize_annotation_metadata(
            incoming_metadata,
            canonical_id=normalized_canonical_id,
        )
        incoming_source_refs = _normalize_source_refs(source_refs)

        now = datetime.now(UTC)
        added_timestamp = now.astimezone(UTC).isoformat()
        updated_timestamp = now.astimezone(UTC).isoformat()

        with self._db.connection() as conn:
            existing_row = _find_existing_item_row(
                conn,
                canonical_id=normalized_canonical_id,
                domain=normalized_domain,
                normalized_title=normalized_title,
                year=_int_from_metadata(incoming_metadata.get("year")),
            )
            if existing_row is None:
                item_id = f"bucket_{uuid4().hex}"
                conn.execute(
                    """
                    INSERT INTO bucket_items (
                        id, title, normalized_title, domain, status, canonical_id, metadata_json,
                        source_refs_json, added_at, updated_at, completed_at, last_recommended_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        item_id,
                        title.strip() or "Untitled",
                        normalized_title,
                        normalized_domain,
                        ACTIVE_STATUS,
                        normalized_canonical_id,
                        _dump_json(incoming_metadata),
                        _dump_json(incoming_source_refs),
                        added_timestamp,
                        updated_timestamp,
                    ),
                )
                created = _get_item_with_conn(conn, item_id)
                if created is None:
                    raise RuntimeError("Bucket item was not found after insert")
                return created, "created"

            existing = _row_to_item(existing_row)
            merged_metadata = _merge_item_metadata(
                base=existing.metadata,
                notes=notes,
                year=year,
                duration_minutes=duration_minutes,
                rating=rating,
                popularity=popularity,
                genres=genres,
                tags=tags,
                providers=providers,
                external_url=external_url,
                confidence=confidence,
                metadata=metadata,
            )
            merged_canonical_id = normalized_canonical_id or existing.canonical_id
            merged_metadata = _normalize_annotation_metadata(
                merged_metadata,
                canonical_id=merged_canonical_id,
            )
            merged_source_refs = _merge_source_refs(existing.source_refs, incoming_source_refs)
            merged_title = title.strip() or existing.title
            merged_normalized_title = _normalize_title(merged_title)

            if (
                existing.status == ACTIVE_STATUS
                and merged_title == existing.title
                and merged_normalized_title == existing.normalized_title
                and normalized_domain == existing.domain
                and merged_canonical_id == existing.canonical_id
                and merged_metadata == existing.metadata
                and merged_source_refs == existing.source_refs
            ):
                return existing, "already_exists"

            conn.execute(
                """
                UPDATE bucket_items
                SET
                    title = ?,
                    normalized_title = ?,
                    domain = ?,
                    status = ?,
                    canonical_id = ?,
                    metadata_json = ?,
                    source_refs_json = ?,
                    updated_at = ?,
                    completed_at = NULL
                WHERE id = ?
                """,
                (
                    merged_title,
                    merged_normalized_title,
                    normalized_domain,
                    ACTIVE_STATUS,
                    merged_canonical_id,
                    _dump_json(merged_metadata),
                    _dump_json(merged_source_refs),
                    updated_timestamp,
                    existing.item_id,
                ),
            )

            refreshed = _get_item_with_conn(conn, existing.item_id)
            if refreshed is None:
                raise RuntimeError("Bucket item was not found after update")
            action = "reactivated" if existing.status != ACTIVE_STATUS else "merged"
            return refreshed, action

    def update_item(
        self,
        *,
        item_id: str,
        title: str | None = None,
        domain: str | None = None,
        notes: str | None = None,
        year: int | None = None,
        duration_minutes: int | None = None,
        rating: float | None = None,
        popularity: float | None = None,
        genres: list[str] | None = None,
        tags: list[str] | None = None,
        providers: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        source_refs: list[dict[str, str]] | None = None,
        canonical_id: str | None = None,
        external_url: str | None = None,
        confidence: float | None = None,
    ) -> BucketItem | None:
        existing = self.get_item(item_id)
        if existing is None:
            return None

        updated_title = (
            title.strip() if isinstance(title, str) and title.strip() else existing.title
        )
        updated_domain = _normalize_domain(domain or existing.domain)
        updated_canonical_id = _normalize_optional_text(canonical_id) or existing.canonical_id
        updated_source_refs = _merge_source_refs(existing.source_refs, source_refs or [])
        updated_metadata = _merge_item_metadata(
            base=existing.metadata,
            notes=notes,
            year=year,
            duration_minutes=duration_minutes,
            rating=rating,
            popularity=popularity,
            genres=genres,
            tags=tags,
            providers=providers,
            external_url=external_url,
            confidence=confidence,
            metadata=(metadata or {}),
        )
        updated_metadata = _normalize_annotation_metadata(
            updated_metadata,
            canonical_id=updated_canonical_id,
        )

        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE bucket_items
                SET
                    title = ?,
                    normalized_title = ?,
                    domain = ?,
                    canonical_id = ?,
                    metadata_json = ?,
                    source_refs_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    updated_title,
                    _normalize_title(updated_title),
                    updated_domain,
                    updated_canonical_id,
                    _dump_json(updated_metadata),
                    _dump_json(updated_source_refs),
                    utc_now_iso(),
                    item_id,
                ),
            )
        return self.get_item(item_id)

    def mark_completed(self, item_id: str) -> BucketItem | None:
        with self._db.connection() as conn:
            now = utc_now_iso()
            cursor = conn.execute(
                """
                UPDATE bucket_items
                SET status = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (COMPLETED_STATUS, now, now, item_id),
            )
            if cursor.rowcount <= 0:
                return None
        return self.get_item(item_id)

    def get_item(self, item_id: str) -> BucketItem | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM bucket_items WHERE id = ? LIMIT 1",
                (item_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_item(row)

    def find_confident_active_match(
        self,
        *,
        title: str,
        domain: str,
        year: int | None,
        canonical_id: str | None,
    ) -> BucketItem | None:
        normalized_domain = _normalize_domain(domain)
        normalized_title = _normalize_title(title)
        normalized_canonical_id = _normalize_optional_text(canonical_id)

        with self._db.connection() as conn:
            if normalized_canonical_id is not None:
                canonical_rows = conn.execute(
                    """
                    SELECT *
                    FROM bucket_items
                    WHERE status = ? AND canonical_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 2
                    """,
                    (ACTIVE_STATUS, normalized_canonical_id),
                ).fetchall()
                if len(canonical_rows) == 1:
                    return _row_to_item(canonical_rows[0])
                if len(canonical_rows) > 1:
                    return None

            rows = conn.execute(
                """
                SELECT *
                FROM bucket_items
                WHERE status = ? AND domain = ? AND normalized_title = ?
                ORDER BY updated_at DESC
                LIMIT 20
                """,
                (ACTIVE_STATUS, normalized_domain, normalized_title),
            ).fetchall()

        if not rows:
            return None

        candidates = [_row_to_item(row) for row in rows]

        if year is not None:
            year_matches = [candidate for candidate in candidates if candidate.year == year]
            if len(year_matches) == 1:
                return year_matches[0]
            return None

        if len(candidates) == 1:
            return candidates[0]

        known_canonical_ids = {
            candidate.canonical_id for candidate in candidates if candidate.canonical_id
        }
        if len(known_canonical_ids) == 1:
            return candidates[0]
        return None

    def list_items(self, limit: int = 1000) -> list[BucketItem]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM bucket_items
                ORDER BY added_at DESC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [_row_to_item(row) for row in rows]

    def list_unannotated_active_items(self, limit: int = 50) -> list[BucketItem]:
        requested = max(1, limit)
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM bucket_items
                WHERE status = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (ACTIVE_STATUS, max(50, requested * 6)),
            ).fetchall()
        items = [_row_to_item(row) for row in rows]
        pending = [item for item in items if not item.is_annotated]
        return pending[:requested]

    def search_items(
        self,
        *,
        query: str | None,
        domain: str | None,
        statuses: set[str],
        min_duration_minutes: int | None,
        max_duration_minutes: int | None,
        genres: list[str],
        min_rating: float | None,
        limit: int,
    ) -> list[BucketItem]:
        normalized_statuses = sorted(
            {status.strip().lower() for status in statuses if status.strip()}
        )
        if not normalized_statuses:
            normalized_statuses = [ACTIVE_STATUS]

        clauses = [f"status IN ({', '.join('?' for _ in normalized_statuses)})"]
        params: list[Any] = list(normalized_statuses)

        normalized_domain = _normalize_optional_text(domain)
        if normalized_domain is not None:
            clauses.append("domain = ?")
            params.append(_normalize_domain(normalized_domain))

        where_clause = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT * FROM bucket_items WHERE {where_clause} ORDER BY updated_at DESC LIMIT ?"
        params.append(max(10, limit * 10))

        with self._db.connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()

        candidate_items = [_row_to_item(row) for row in rows]
        normalized_query = _normalize_optional_text(query)
        normalized_genres = [genre.lower().strip() for genre in genres if genre.strip()]
        filtered: list[BucketItem] = []
        for item in candidate_items:
            if normalized_query is not None:
                searchable_text = f"{item.title}\n{item.notes}".lower()
                if normalized_query.lower() not in searchable_text:
                    continue
            if (
                min_duration_minutes is not None
                and item.duration_minutes is not None
                and item.duration_minutes < min_duration_minutes
            ):
                continue
            if (
                max_duration_minutes is not None
                and item.duration_minutes is not None
                and item.duration_minutes > max_duration_minutes
            ):
                continue
            if min_rating is not None and item.rating is not None and item.rating < min_rating:
                continue
            if normalized_genres and not _genres_overlap(item.genres, normalized_genres):
                continue
            filtered.append(item)
            if len(filtered) >= max(1, limit):
                break
        return filtered

    def track_recommendations(self, item_ids: list[str]) -> None:
        if not item_ids:
            return
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.executemany(
                """
                UPDATE bucket_items
                SET last_recommended_at = ?, updated_at = ?
                WHERE id = ?
                """,
                [(now, now, item_id) for item_id in item_ids],
            )

    def build_health_report(
        self,
        *,
        stale_after_days: int,
        quick_win_max_minutes: int,
        quick_win_min_rating: float,
        limit: int,
    ) -> dict[str, Any]:
        items = self.list_items(limit=5000)
        now = datetime.now(UTC)
        active_items = [item for item in items if item.status == ACTIVE_STATUS]
        completed_items = [item for item in items if item.status == COMPLETED_STATUS]

        by_domain: dict[str, int] = {}
        for item in active_items:
            by_domain[item.domain] = by_domain.get(item.domain, 0) + 1

        stale_items: list[dict[str, Any]] = []
        for item in active_items:
            waiting_days = _waiting_days(item, now)
            if waiting_days < stale_after_days:
                continue
            stale_items.append(
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "domain": item.domain,
                    "waiting_days": waiting_days,
                    "duration_minutes": item.duration_minutes,
                    "rating": item.rating,
                }
            )
        stale_items.sort(key=lambda entry: int(entry["waiting_days"]), reverse=True)
        stale_items = stale_items[: max(1, limit)]

        missing_metadata = {
            "duration_missing": 0,
            "genres_missing": 0,
            "rating_missing": 0,
        }
        for item in active_items:
            if item.domain in {"movie", "tv", "show"}:
                if item.duration_minutes is None:
                    missing_metadata["duration_missing"] += 1
                if not item.genres:
                    missing_metadata["genres_missing"] += 1
                if item.rating is None:
                    missing_metadata["rating_missing"] += 1

        duplicates = _duplicate_groups(active_items, limit=limit)

        quick_wins: list[dict[str, Any]] = []
        for item in active_items:
            if item.duration_minutes is None or item.rating is None:
                continue
            if item.duration_minutes > quick_win_max_minutes:
                continue
            if item.rating < quick_win_min_rating:
                continue
            quick_wins.append(
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "duration_minutes": item.duration_minutes,
                    "rating": item.rating,
                    "waiting_days": _waiting_days(item, now),
                }
            )
        quick_wins.sort(
            key=lambda entry: (
                float(entry["rating"]),
                int(entry["waiting_days"]),
            ),
            reverse=True,
        )
        quick_wins = quick_wins[: max(1, limit)]

        avg_waiting_days = 0.0
        if active_items:
            avg_waiting_days = sum(_waiting_days(item, now) for item in active_items) / len(
                active_items
            )

        suggestions = _build_health_suggestions(
            active_count=len(active_items),
            stale_count=len(stale_items),
            metadata_gaps=missing_metadata,
        )

        return {
            "totals": {
                "all": len(items),
                "active": len(active_items),
                "completed": len(completed_items),
            },
            "by_domain": by_domain,
            "average_waiting_days_active": round(avg_waiting_days, 2),
            "stale_after_days": stale_after_days,
            "stale_items": stale_items,
            "missing_metadata": missing_metadata,
            "duplicate_candidates": duplicates,
            "quick_wins": quick_wins,
            "suggestions": suggestions,
        }


def _find_existing_item_row(
    conn: Connection,
    *,
    canonical_id: str | None,
    domain: str,
    normalized_title: str,
    year: int | None,
) -> Row | None:
    if canonical_id is not None:
        canonical_match = conn.execute(
            "SELECT * FROM bucket_items WHERE canonical_id = ? LIMIT 1",
            (canonical_id,),
        ).fetchone()
        if canonical_match is not None:
            return canonical_match

    rows = conn.execute(
        """
        SELECT *
        FROM bucket_items
        WHERE domain = ? AND normalized_title = ?
        ORDER BY added_at DESC
        LIMIT 20
        """,
        (domain, normalized_title),
    ).fetchall()
    if not rows:
        return None

    if year is not None:
        for row in rows:
            candidate = _row_to_item(row)
            if candidate.year == year:
                return row

    if year is None:
        for row in rows:
            candidate = _row_to_item(row)
            if candidate.year is None:
                return row

    return rows[0]


def _row_to_item(row: Row) -> BucketItem:
    return BucketItem(
        item_id=str(row["id"]),
        title=str(row["title"]),
        normalized_title=str(row["normalized_title"]),
        domain=str(row["domain"]),
        status=str(row["status"]),
        canonical_id=_text_or_none(row["canonical_id"]),
        metadata=_load_object_dict(row["metadata_json"]),
        source_refs=_load_source_refs(row["source_refs_json"]),
        added_at=_parse_iso_datetime(str(row["added_at"])),
        updated_at=_parse_iso_datetime(str(row["updated_at"])),
        completed_at=_parse_iso_datetime_optional(row["completed_at"]),
        last_recommended_at=_parse_iso_datetime_optional(row["last_recommended_at"]),
    )


def _get_item_with_conn(conn: Connection, item_id: str) -> BucketItem | None:
    row = conn.execute(
        "SELECT * FROM bucket_items WHERE id = ? LIMIT 1",
        (item_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_item(row)


def _merge_item_metadata(
    *,
    base: dict[str, Any],
    notes: str | None,
    year: int | None,
    duration_minutes: int | None,
    rating: float | None,
    popularity: float | None,
    genres: list[str] | None,
    tags: list[str] | None,
    providers: list[str] | None,
    external_url: str | None,
    confidence: float | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(base)
    merged.update(metadata)

    existing_notes = _text_or_none(merged.get("notes")) or ""
    merged_notes = _merge_notes(existing_notes, notes)
    if merged_notes:
        merged["notes"] = merged_notes

    if year is not None:
        merged["year"] = year
    if duration_minutes is not None:
        merged["duration_minutes"] = duration_minutes
    if rating is not None:
        merged["rating"] = rating
    if popularity is not None:
        merged["popularity"] = popularity

    merged["genres"] = _merge_str_lists(_str_list_from_metadata(merged.get("genres")), genres)
    merged["tags"] = _merge_str_lists(_str_list_from_metadata(merged.get("tags")), tags)
    merged["providers"] = _merge_str_lists(
        _str_list_from_metadata(merged.get("providers")),
        providers,
    )

    normalized_external_url = _normalize_optional_text(external_url) or _text_or_none(
        merged.get("external_url")
    )
    if normalized_external_url is not None:
        merged["external_url"] = normalized_external_url

    if confidence is not None:
        merged["confidence"] = confidence
    elif "confidence" in merged:
        existing_confidence = _float_from_metadata(merged.get("confidence"))
        if existing_confidence is not None:
            merged["confidence"] = existing_confidence
        else:
            merged.pop("confidence", None)

    return merged


def _normalize_annotation_metadata(
    metadata: dict[str, Any],
    *,
    canonical_id: str | None,
) -> dict[str, Any]:
    normalized = dict(metadata)
    normalized["annotation_status"] = _annotation_status(normalized, canonical_id=canonical_id)
    return normalized


def _annotation_status(
    metadata: dict[str, Any],
    *,
    canonical_id: str | None,
) -> str:
    raw_status = metadata.get("annotation_status")
    if isinstance(raw_status, str):
        normalized_status = raw_status.strip().lower()
        if normalized_status in {"pending", "annotated", "failed"}:
            return normalized_status

    if canonical_id is not None:
        return "annotated"

    has_structured_signal = any(
        (
            _int_from_metadata(metadata.get("year")) is not None,
            _int_from_metadata(metadata.get("duration_minutes")) is not None,
            _float_from_metadata(metadata.get("rating")) is not None,
            _str_list_from_metadata(metadata.get("genres")),
            _str_list_from_metadata(metadata.get("providers")),
            _text_or_none(metadata.get("external_url")) is not None,
        )
    )
    return "annotated" if has_structured_signal else "pending"


def _genres_overlap(item_genres: list[str], target_genres: list[str]) -> bool:
    item_genre_set = {genre.lower().strip() for genre in item_genres if genre.strip()}
    if not item_genre_set:
        return False
    return any(genre in item_genre_set for genre in target_genres)


def _duplicate_groups(items: list[BucketItem], *, limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[BucketItem]] = {}
    for item in items:
        year_key = str(item.year) if item.year is not None else "-"
        key = f"{item.domain}:{item.normalized_title}:{year_key}"
        grouped.setdefault(key, []).append(item)

    duplicates: list[dict[str, Any]] = []
    for key, grouped_items in grouped.items():
        if len(grouped_items) <= 1:
            continue
        duplicates.append(
            {
                "key": key,
                "count": len(grouped_items),
                "items": [{"item_id": item.item_id, "title": item.title} for item in grouped_items],
            }
        )
    duplicates.sort(key=lambda entry: int(entry["count"]), reverse=True)
    return duplicates[: max(1, limit)]


def _build_health_suggestions(
    *,
    active_count: int,
    stale_count: int,
    metadata_gaps: dict[str, int],
) -> list[str]:
    suggestions: list[str] = []
    if active_count >= 50:
        suggestions.append("Your bucket list is large; consider weekly cleanup to keep momentum.")
    if stale_count > 0:
        suggestions.append(
            "Promote stale items into a short-term queue so they do not linger indefinitely."
        )
    if metadata_gaps["duration_missing"] > 0:
        suggestions.append("Fill missing durations to improve time-based recommendations.")
    if metadata_gaps["genres_missing"] > 0:
        suggestions.append("Fill missing genres to improve similarity and mood filtering.")
    if metadata_gaps["rating_missing"] > 0:
        suggestions.append("Fill missing ratings to improve quality-based ranking.")
    if not suggestions:
        suggestions.append("Bucket list health looks good. Keep cycling through quick wins.")
    return suggestions


def _waiting_days(item: BucketItem, now: datetime) -> int:
    return max(0, int((now - item.added_at.astimezone(UTC)).days))


def _normalize_title(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "untitled"


def _normalize_domain(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return "general"
    aliases = {
        "film": "movie",
        "tv_show": "tv",
        "show": "tv",
        "series": "tv",
        "book": "book",
        "place": "place",
        "trip": "travel",
    }
    return aliases.get(normalized, normalized)


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _normalize_source_refs(source_refs: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source_ref in source_refs:
        ref_type = source_ref.get("type")
        ref_id = source_ref.get("id")
        if not isinstance(ref_type, str) or not isinstance(ref_id, str):
            continue
        key = (ref_type.strip(), ref_id.strip())
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        normalized.append({"type": key[0], "id": key[1]})
    return normalized


def _merge_source_refs(
    first: list[dict[str, str]],
    second: list[dict[str, str]],
) -> list[dict[str, str]]:
    return _normalize_source_refs([*first, *second])


def _merge_notes(existing: str, incoming: str | None) -> str:
    if incoming is None:
        return existing
    normalized_incoming = incoming.strip()
    if not normalized_incoming:
        return existing
    if not existing.strip():
        return normalized_incoming
    if normalized_incoming in existing:
        return existing
    return f"{existing.rstrip()}\n\n{normalized_incoming}"


def _merge_str_lists(existing: list[str], incoming: list[str] | None) -> list[str]:
    if incoming is None:
        return _dedupe_nonempty(existing)
    return _dedupe_nonempty([*existing, *incoming])


def _dedupe_nonempty(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _load_object_dict(raw: object) -> dict[str, Any]:
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        raw_dict = cast(dict[object, object], parsed)
        output: dict[str, Any] = {}
        for key, value in raw_dict.items():
            if isinstance(key, str):
                output[key] = value
        return output
    return {}


def _str_list_from_metadata(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in cast(list[object], value):
        if isinstance(item, str) and item.strip():
            output.append(item.strip())
    return _dedupe_nonempty(output)


def _int_from_metadata(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _float_from_metadata(value: object) -> float | None:
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _load_source_refs(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    refs: list[dict[str, str]] = []
    for item in cast(list[object], parsed):
        if not isinstance(item, dict):
            continue
        raw_item = cast(dict[object, object], item)
        ref_type = raw_item.get("type")
        ref_id = raw_item.get("id")
        if isinstance(ref_type, str) and isinstance(ref_id, str):
            refs.append({"type": ref_type, "id": ref_id})
    return _normalize_source_refs(refs)


def _dump_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def _parse_iso_datetime(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_iso_datetime_optional(raw: object) -> datetime | None:
    text = _text_or_none(raw)
    if text is None:
        return None
    try:
        return _parse_iso_datetime(text)
    except ValueError:
        return None


def _text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped
