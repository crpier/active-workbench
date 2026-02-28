from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection, Row
from typing import Any, cast
from urllib.parse import urlparse
from uuid import uuid4

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database

ARTICLE_STATUS_CAPTURED = "captured"
ARTICLE_STATUS_PROCESSING = "processing"
ARTICLE_STATUS_READABLE = "readable"
ARTICLE_STATUS_FAILED = "failed"

ARTICLE_READ_STATE_UNREAD = "unread"
ARTICLE_READ_STATE_IN_PROGRESS = "in_progress"
ARTICLE_READ_STATE_READ = "read"

ARTICLE_JOB_STATUS_QUEUED = "queued"
ARTICLE_JOB_STATUS_RUNNING = "running"
ARTICLE_JOB_STATUS_SUCCEEDED = "succeeded"
ARTICLE_JOB_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class ArticleRecord:
    article_id: str
    bucket_item_id: str
    source_url: str
    canonical_url: str
    title: str | None
    author: str | None
    site_name: str | None
    published_at: str | None
    captured_at: datetime
    status: str
    read_state: str
    estimated_read_minutes: int | None
    progress_percent: int
    last_error_code: str | None
    last_error_message: str | None
    last_error_at: datetime | None
    extraction_method: str | None
    llm_polished: bool
    provenance: dict[str, Any]
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def domain_host(self) -> str | None:
        host = urlparse(self.canonical_url).hostname
        if not isinstance(host, str):
            return None
        normalized = host.strip().lower()
        return normalized or None


@dataclass(frozen=True)
class ArticleSnapshot:
    snapshot_id: str
    article_id: str
    snapshot_type: str
    content_text: str
    content_hash: str
    extractor: str
    extractor_version: str | None
    created_at: datetime


@dataclass(frozen=True)
class ArticleJob:
    job_id: str
    article_id: str
    job_type: str
    status: str
    attempts: int
    next_run_at: datetime
    last_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ArticleDomainThrottle:
    domain: str
    next_allowed_at: datetime
    backoff_level: int
    last_http_status: int | None
    updated_at: datetime


class ArticleRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create_article(
        self,
        *,
        bucket_item_id: str,
        source_url: str,
        canonical_url: str,
        title: str | None,
        provenance: dict[str, Any],
    ) -> ArticleRecord:
        now_iso = utc_now_iso()
        article_id = f"article_{uuid4().hex}"
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO articles (
                    id,
                    bucket_item_id,
                    source_url,
                    canonical_url,
                    title,
                    author,
                    site_name,
                    published_at,
                    captured_at,
                    status,
                    read_state,
                    estimated_read_minutes,
                    progress_percent,
                    last_error_code,
                    last_error_message,
                    last_error_at,
                    extraction_method,
                    llm_polished,
                    provenance_json,
                    deleted_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, NULL, 0, NULL, NULL, NULL, NULL, 0, ?, NULL, ?, ?)
                """,
                (
                    article_id,
                    bucket_item_id,
                    source_url,
                    canonical_url,
                    _normalize_optional_text(title),
                    now_iso,
                    ARTICLE_STATUS_CAPTURED,
                    ARTICLE_READ_STATE_UNREAD,
                    _dump_json(provenance),
                    now_iso,
                    now_iso,
                ),
            )
            created = _get_article_with_conn(conn, article_id)
        if created is None:
            raise RuntimeError("Article was not found after insert")
        return created

    def get_article(self, article_id: str, *, include_deleted: bool = False) -> ArticleRecord | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM articles
                WHERE id = ?
                LIMIT 1
                """,
                (article_id,),
            ).fetchone()
        if row is None:
            return None
        article = _row_to_article(row)
        if article.deleted_at is not None and not include_deleted:
            return None
        return article

    def get_article_by_bucket_item_id(
        self,
        bucket_item_id: str,
        *,
        include_deleted: bool = False,
    ) -> ArticleRecord | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM articles
                WHERE bucket_item_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (bucket_item_id,),
            ).fetchone()
        if row is None:
            return None
        article = _row_to_article(row)
        if article.deleted_at is not None and not include_deleted:
            return None
        return article

    def find_active_by_url(self, normalized_url: str) -> ArticleRecord | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM articles
                WHERE deleted_at IS NULL
                  AND (canonical_url = ? OR source_url = ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (normalized_url, normalized_url),
            ).fetchone()
        if row is None:
            return None
        return _row_to_article(row)

    def list_articles(
        self,
        *,
        statuses: set[str] | None = None,
        read_states: set[str] | None = None,
        domain_host: str | None = None,
        limit: int,
        cursor: int,
    ) -> list[ArticleRecord]:
        status_values = sorted(
            status.strip().lower()
            for status in (statuses or set())
            if status.strip()
        )
        read_state_values = sorted(
            read_state.strip().lower()
            for read_state in (read_states or set())
            if read_state.strip()
        )

        clauses = ["deleted_at IS NULL"]
        params: list[Any] = []
        if status_values:
            clauses.append(f"status IN ({', '.join('?' for _ in status_values)})")
            params.extend(status_values)
        if read_state_values:
            clauses.append(f"read_state IN ({', '.join('?' for _ in read_state_values)})")
            params.extend(read_state_values)

        normalized_host = _normalize_optional_text(domain_host)
        if normalized_host is not None:
            clauses.append("lower(canonical_url) LIKE ?")
            params.append(f"%://{normalized_host}/%")

        where_sql = " AND ".join(clauses)
        params.append(max(1, min(limit, 200)))
        params.append(max(0, cursor))
        with self._db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM articles
                WHERE {where_sql}
                ORDER BY captured_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
        return [_row_to_article(row) for row in rows]

    def update_article_processing_status(self, article_id: str) -> ArticleRecord | None:
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE articles
                SET
                    status = ?,
                    last_error_code = NULL,
                    last_error_message = NULL,
                    last_error_at = NULL,
                    updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (
                    ARTICLE_STATUS_PROCESSING,
                    now_iso,
                    article_id,
                ),
            )
            if cursor.rowcount <= 0:
                return None
            return _get_article_with_conn(conn, article_id)

    def update_article_readable(
        self,
        *,
        article_id: str,
        canonical_url: str,
        title: str | None,
        author: str | None,
        site_name: str | None,
        published_at: str | None,
        extraction_method: str,
        llm_polished: bool,
        estimated_read_minutes: int,
        provenance: dict[str, Any],
    ) -> ArticleRecord | None:
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE articles
                SET
                    canonical_url = ?,
                    title = ?,
                    author = ?,
                    site_name = ?,
                    published_at = ?,
                    status = ?,
                    extraction_method = ?,
                    llm_polished = ?,
                    estimated_read_minutes = ?,
                    progress_percent = CASE WHEN read_state = ? THEN 100 ELSE progress_percent END,
                    provenance_json = ?,
                    last_error_code = NULL,
                    last_error_message = NULL,
                    last_error_at = NULL,
                    updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (
                    canonical_url,
                    _normalize_optional_text(title),
                    _normalize_optional_text(author),
                    _normalize_optional_text(site_name),
                    _normalize_optional_text(published_at),
                    ARTICLE_STATUS_READABLE,
                    extraction_method.strip(),
                    1 if llm_polished else 0,
                    max(1, estimated_read_minutes),
                    ARTICLE_READ_STATE_READ,
                    _dump_json(provenance),
                    now_iso,
                    article_id,
                ),
            )
            if cursor.rowcount <= 0:
                return None
            return _get_article_with_conn(conn, article_id)

    def update_article_failed(
        self,
        *,
        article_id: str,
        error_code: str,
        error_message: str,
    ) -> ArticleRecord | None:
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE articles
                SET
                    status = ?,
                    last_error_code = ?,
                    last_error_message = ?,
                    last_error_at = ?,
                    updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (
                    ARTICLE_STATUS_FAILED,
                    _normalize_optional_text(error_code) or "unknown_error",
                    _normalize_optional_text(error_message) or "Unknown error",
                    now_iso,
                    now_iso,
                    article_id,
                ),
            )
            if cursor.rowcount <= 0:
                return None
            return _get_article_with_conn(conn, article_id)

    def update_read_state(
        self,
        *,
        article_id: str,
        read_state: str,
        progress_percent: int | None,
    ) -> ArticleRecord | None:
        normalized_state = read_state.strip().lower()
        if normalized_state not in {
            ARTICLE_READ_STATE_UNREAD,
            ARTICLE_READ_STATE_IN_PROGRESS,
            ARTICLE_READ_STATE_READ,
        }:
            return None

        progress_value = progress_percent
        if progress_value is None:
            if normalized_state == ARTICLE_READ_STATE_UNREAD:
                progress_value = 0
            elif normalized_state == ARTICLE_READ_STATE_READ:
                progress_value = 100
        if progress_value is not None:
            progress_value = max(0, min(100, int(progress_value)))

        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE articles
                SET
                    read_state = ?,
                    progress_percent = COALESCE(?, progress_percent),
                    updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (
                    normalized_state,
                    progress_value,
                    now_iso,
                    article_id,
                ),
            )
            if cursor.rowcount <= 0:
                return None
            return _get_article_with_conn(conn, article_id)

    def mark_deleted(self, article_id: str) -> ArticleRecord | None:
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE articles
                SET
                    deleted_at = ?,
                    updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (now_iso, now_iso, article_id),
            )
            if cursor.rowcount <= 0:
                return None
            conn.execute(
                "DELETE FROM article_snapshots WHERE article_id = ?",
                (article_id,),
            )
            return _get_article_with_conn(conn, article_id)

    def add_snapshot(
        self,
        *,
        article_id: str,
        snapshot_type: str,
        content_text: str,
        content_hash: str,
        extractor: str,
        extractor_version: str | None,
    ) -> ArticleSnapshot:
        snapshot_id = f"asnap_{uuid4().hex}"
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO article_snapshots (
                    id,
                    article_id,
                    snapshot_type,
                    content_text,
                    content_hash,
                    extractor,
                    extractor_version,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    article_id,
                    snapshot_type.strip().lower(),
                    content_text,
                    content_hash.strip(),
                    extractor.strip().lower(),
                    _normalize_optional_text(extractor_version),
                    now_iso,
                ),
            )
            row = conn.execute(
                "SELECT * FROM article_snapshots WHERE id = ? LIMIT 1",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Article snapshot was not found after insert")
        return _row_to_snapshot(row)

    def get_latest_snapshot(self, *, article_id: str, snapshot_type: str) -> ArticleSnapshot | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM article_snapshots
                WHERE article_id = ? AND snapshot_type = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (article_id, snapshot_type.strip().lower()),
            ).fetchone()
        if row is None:
            return None
        return _row_to_snapshot(row)

    def enqueue_job(
        self,
        *,
        article_id: str,
        job_type: str,
        next_run_at: datetime | None = None,
    ) -> ArticleJob:
        now = datetime.now(UTC)
        job_id = f"ajob_{uuid4().hex}"
        next_run = now if next_run_at is None else next_run_at.astimezone(UTC)
        with self._db.connection() as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM article_jobs
                WHERE article_id = ?
                  AND job_type = ?
                  AND status IN (?, ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (
                    article_id,
                    job_type.strip().lower(),
                    ARTICLE_JOB_STATUS_QUEUED,
                    ARTICLE_JOB_STATUS_RUNNING,
                ),
            ).fetchone()
            if existing is not None:
                return _row_to_job(existing)

            conn.execute(
                """
                INSERT INTO article_jobs (
                    id,
                    article_id,
                    job_type,
                    status,
                    attempts,
                    next_run_at,
                    last_error,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, 0, ?, NULL, ?, ?)
                """,
                (
                    job_id,
                    article_id,
                    job_type.strip().lower(),
                    ARTICLE_JOB_STATUS_QUEUED,
                    next_run.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM article_jobs WHERE id = ? LIMIT 1",
                (job_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Article job was not found after insert")
        return _row_to_job(row)

    def claim_due_jobs(self, *, limit: int) -> list[ArticleJob]:
        now_iso = utc_now_iso()
        claimed: list[ArticleJob] = []
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM article_jobs
                WHERE status = ?
                  AND next_run_at <= ?
                ORDER BY next_run_at ASC, created_at ASC
                LIMIT ?
                """,
                (
                    ARTICLE_JOB_STATUS_QUEUED,
                    now_iso,
                    max(1, min(limit, 100)),
                ),
            ).fetchall()
            for row in rows:
                job_id = str(row["id"])
                updated = conn.execute(
                    """
                    UPDATE article_jobs
                    SET
                        status = ?,
                        attempts = attempts + 1,
                        updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        ARTICLE_JOB_STATUS_RUNNING,
                        now_iso,
                        job_id,
                        ARTICLE_JOB_STATUS_QUEUED,
                    ),
                )
                if updated.rowcount <= 0:
                    continue
                claimed_row = conn.execute(
                    "SELECT * FROM article_jobs WHERE id = ? LIMIT 1",
                    (job_id,),
                ).fetchone()
                if claimed_row is not None:
                    claimed.append(_row_to_job(claimed_row))
        return claimed

    def mark_job_succeeded(self, job_id: str) -> None:
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE article_jobs
                SET
                    status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    ARTICLE_JOB_STATUS_SUCCEEDED,
                    now_iso,
                    job_id,
                ),
            )

    def mark_job_retry(self, *, job_id: str, retry_after_seconds: int, last_error: str) -> None:
        now = datetime.now(UTC)
        next_run_at = now + timedelta(seconds=max(1, retry_after_seconds))
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE article_jobs
                SET
                    status = ?,
                    next_run_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    ARTICLE_JOB_STATUS_QUEUED,
                    next_run_at.isoformat(),
                    _normalize_optional_text(last_error),
                    now.isoformat(),
                    job_id,
                ),
            )

    def mark_job_failed(self, *, job_id: str, last_error: str) -> None:
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE article_jobs
                SET
                    status = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    ARTICLE_JOB_STATUS_FAILED,
                    _normalize_optional_text(last_error),
                    now_iso,
                    job_id,
                ),
            )

    def get_domain_throttle(self, *, domain: str) -> ArticleDomainThrottle | None:
        normalized_domain = _normalize_optional_text(domain)
        if normalized_domain is None:
            return None
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM article_domain_throttle
                WHERE domain = ?
                LIMIT 1
                """,
                (normalized_domain.lower(),),
            ).fetchone()
        if row is None:
            return None
        return _row_to_domain_throttle(row)

    def upsert_domain_throttle(
        self,
        *,
        domain: str,
        next_allowed_at: datetime,
        backoff_level: int,
        last_http_status: int | None,
    ) -> ArticleDomainThrottle:
        normalized_domain = _normalize_optional_text(domain)
        if normalized_domain is None:
            raise ValueError("domain is required")
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO article_domain_throttle (
                    domain,
                    next_allowed_at,
                    backoff_level,
                    last_http_status,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalized_domain.lower(),
                    next_allowed_at.astimezone(UTC).isoformat(),
                    max(1, backoff_level),
                    last_http_status,
                    now_iso,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM article_domain_throttle
                WHERE domain = ?
                LIMIT 1
                """,
                (normalized_domain.lower(),),
            ).fetchone()
        if row is None:
            raise RuntimeError("Domain throttle row missing after upsert")
        return _row_to_domain_throttle(row)

    def clear_domain_throttle(self, *, domain: str) -> None:
        normalized_domain = _normalize_optional_text(domain)
        if normalized_domain is None:
            return
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM article_domain_throttle WHERE domain = ?",
                (normalized_domain.lower(),),
            )


def _get_article_with_conn(conn: Connection, article_id: str) -> ArticleRecord | None:
    row = conn.execute(
        "SELECT * FROM articles WHERE id = ? LIMIT 1",
        (article_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_article(row)


def _row_to_article(row: Row) -> ArticleRecord:
    return ArticleRecord(
        article_id=str(row["id"]),
        bucket_item_id=str(row["bucket_item_id"]),
        source_url=str(row["source_url"]),
        canonical_url=str(row["canonical_url"]),
        title=_normalize_optional_text(row["title"]),
        author=_normalize_optional_text(row["author"]),
        site_name=_normalize_optional_text(row["site_name"]),
        published_at=_normalize_optional_text(row["published_at"]),
        captured_at=_parse_iso_datetime(str(row["captured_at"])),
        status=str(row["status"]),
        read_state=str(row["read_state"]),
        estimated_read_minutes=_to_optional_int(row["estimated_read_minutes"]),
        progress_percent=_to_optional_int(row["progress_percent"]) or 0,
        last_error_code=_normalize_optional_text(row["last_error_code"]),
        last_error_message=_normalize_optional_text(row["last_error_message"]),
        last_error_at=_parse_iso_datetime_optional(row["last_error_at"]),
        extraction_method=_normalize_optional_text(row["extraction_method"]),
        llm_polished=bool(_to_optional_int(row["llm_polished"]) or 0),
        provenance=_load_object_dict(row["provenance_json"]),
        deleted_at=_parse_iso_datetime_optional(row["deleted_at"]),
        created_at=_parse_iso_datetime(str(row["created_at"])),
        updated_at=_parse_iso_datetime(str(row["updated_at"])),
    )


def _row_to_snapshot(row: Row) -> ArticleSnapshot:
    return ArticleSnapshot(
        snapshot_id=str(row["id"]),
        article_id=str(row["article_id"]),
        snapshot_type=str(row["snapshot_type"]),
        content_text=str(row["content_text"]),
        content_hash=str(row["content_hash"]),
        extractor=str(row["extractor"]),
        extractor_version=_normalize_optional_text(row["extractor_version"]),
        created_at=_parse_iso_datetime(str(row["created_at"])),
    )


def _row_to_job(row: Row) -> ArticleJob:
    return ArticleJob(
        job_id=str(row["id"]),
        article_id=str(row["article_id"]),
        job_type=str(row["job_type"]),
        status=str(row["status"]),
        attempts=max(0, _to_optional_int(row["attempts"]) or 0),
        next_run_at=_parse_iso_datetime(str(row["next_run_at"])),
        last_error=_normalize_optional_text(row["last_error"]),
        created_at=_parse_iso_datetime(str(row["created_at"])),
        updated_at=_parse_iso_datetime(str(row["updated_at"])),
    )


def _row_to_domain_throttle(row: Row) -> ArticleDomainThrottle:
    return ArticleDomainThrottle(
        domain=str(row["domain"]),
        next_allowed_at=_parse_iso_datetime(str(row["next_allowed_at"])),
        backoff_level=max(1, _to_optional_int(row["backoff_level"]) or 1),
        last_http_status=_to_optional_int(row["last_http_status"]),
        updated_at=_parse_iso_datetime(str(row["updated_at"])),
    )


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_iso_datetime_optional(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return _parse_iso_datetime(normalized)


def _to_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def _dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _load_object_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    raw = cast(dict[object, object], parsed)
    normalized: dict[str, Any] = {}
    for key, item_value in raw.items():
        if isinstance(key, str):
            normalized[key] = item_value
    return normalized
