from __future__ import annotations

import json
import re
from typing import cast
from uuid import uuid4

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database


class MemoryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create_entry(
        self,
        content: dict[str, object],
        source_refs: list[dict[str, str]],
    ) -> tuple[str, str]:
        memory_id = f"mem_{uuid4().hex}"
        undo_token = f"undo_{uuid4().hex}"
        timestamp = utc_now_iso()

        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_entries
                (id, content_json, source_refs_json, created_at, deleted_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    memory_id,
                    json.dumps(content, sort_keys=True),
                    json.dumps(source_refs, sort_keys=True),
                    timestamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_undo_tokens (undo_token, memory_id, created_at, consumed_at)
                VALUES (?, ?, ?, NULL)
                """,
                (undo_token, memory_id, timestamp),
            )

        return memory_id, undo_token

    def undo(self, undo_token: str) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT memory_id
                FROM memory_undo_tokens
                WHERE undo_token = ? AND consumed_at IS NULL
                """,
                (undo_token,),
            ).fetchone()
            if row is None:
                return None

            memory_id = str(row["memory_id"])
            timestamp = utc_now_iso()

            conn.execute(
                """
                UPDATE memory_undo_tokens
                SET consumed_at = ?
                WHERE undo_token = ?
                """,
                (timestamp, undo_token),
            )
            conn.execute(
                """
                UPDATE memory_entries
                SET deleted_at = ?
                WHERE id = ?
                """,
                (timestamp, memory_id),
            )

        return memory_id

    def list_active_entries(self, limit: int = 20) -> list[dict[str, object]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, content_json, source_refs_json, created_at
                FROM memory_entries
                WHERE deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        entries: list[dict[str, object]] = []
        for row in rows:
            entries.append(
                {
                    "id": str(row["id"]),
                    "content": _load_json_object(str(row["content_json"])),
                    "source_refs": _load_source_refs(str(row["source_refs_json"])),
                    "created_at": str(row["created_at"]),
                }
            )
        return entries

    def delete_entry(self, memory_id: str) -> bool:
        timestamp = utc_now_iso()
        with self._db.connection() as conn:
            result = conn.execute(
                """
                UPDATE memory_entries
                SET deleted_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (timestamp, memory_id),
            )
        return result.rowcount > 0

    def search_active_entries(
        self,
        *,
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
        scan_limit: int = 500,
    ) -> list[dict[str, object]]:
        normalized_query = (query or "").strip().lower()
        query_tokens = [token for token in re.findall(r"[a-z0-9]+", normalized_query) if token]
        required_tags = _normalize_tags(tags or [])

        window_limit = max(limit, scan_limit)
        entries = self.list_active_entries(limit=window_limit)
        scored: list[dict[str, object]] = []

        for entry in entries:
            content = entry.get("content")
            if not isinstance(content, dict):
                continue
            typed_content = cast(dict[str, object], content)

            content_tags = _content_tags(typed_content)
            if required_tags and not (content_tags & required_tags):
                continue

            searchable_text = _memory_search_text(typed_content)
            score = _memory_match_score(
                searchable_text=searchable_text,
                normalized_query=normalized_query,
                query_tokens=query_tokens,
                content_tags=content_tags,
                required_tags=required_tags,
            )
            if query_tokens and score <= 0:
                continue

            scored_entry = dict(entry)
            scored_entry["match_score"] = score
            scored_entry["matched_tags"] = sorted(content_tags & required_tags)
            scored.append(scored_entry)

        scored.sort(key=_memory_sort_key, reverse=True)
        return scored[:limit]


def _memory_sort_key(entry: dict[str, object]) -> tuple[float, str]:
    score_raw = entry.get("match_score")
    score = float(score_raw) if isinstance(score_raw, (int, float)) else 0.0
    created_raw = entry.get("created_at")
    created_at = created_raw if isinstance(created_raw, str) else ""
    return score, created_at


def _load_json_object(raw_value: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    raw_dict = cast(dict[object, object], parsed)
    normalized: dict[str, object] = {}
    for key, value in raw_dict.items():
        if isinstance(key, str):
            normalized[key] = value
    return normalized


def _load_source_refs(raw_value: str) -> list[dict[str, str]]:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    entries: list[dict[str, str]] = []
    for item in cast(list[object], parsed):
        if not isinstance(item, dict):
            continue
        raw_item = cast(dict[object, object], item)
        ref_type = raw_item.get("type")
        ref_id = raw_item.get("id")
        if isinstance(ref_type, str) and isinstance(ref_id, str):
            entries.append({"type": ref_type, "id": ref_id})
    return entries


def _normalize_tags(values: list[str]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        lowered = value.strip().lower()
        if lowered:
            normalized.add(lowered)
    return normalized


def _content_tags(content: dict[str, object]) -> set[str]:
    raw_tags = content.get("tags")
    if not isinstance(raw_tags, list):
        return set()
    tags: list[str] = []
    for item in cast(list[object], raw_tags):
        if isinstance(item, str):
            tags.append(item)
    return _normalize_tags(tags)


def _memory_search_text(content: dict[str, object]) -> str:
    text_parts: list[str] = []
    for key in ("text", "fact", "note", "summary", "title"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            text_parts.append(value.strip())
    text_parts.append(json.dumps(content, sort_keys=True))
    return "\n".join(text_parts).lower()


def _memory_match_score(
    *,
    searchable_text: str,
    normalized_query: str,
    query_tokens: list[str],
    content_tags: set[str],
    required_tags: set[str],
) -> float:
    score = 0.0

    if normalized_query and normalized_query in searchable_text:
        score += 6.0

    for token in query_tokens:
        if token in searchable_text:
            score += 1.5

    if required_tags:
        score += float(len(content_tags & required_tags))
    elif not query_tokens:
        score += 1.0

    return score
