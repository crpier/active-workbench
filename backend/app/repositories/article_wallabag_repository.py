from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Row

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database

SYNC_STATUS_PENDING = "pending"
SYNC_STATUS_SYNCED = "synced"
SYNC_STATUS_FAILED = "failed"

READ_STATE_UNREAD = "unread"
READ_STATE_READ = "read"

JOB_TYPE_PUSH = "push"
JOB_TYPE_PULL = "pull"


@dataclass(frozen=True)
class ArticleWallabagState:
    bucket_item_id: str
    source_url: str
    canonical_url: str | None
    sync_status: str
    wallabag_entry_id: int | None
    wallabag_entry_url: str | None
    read_state: str
    read_at: datetime | None
    sync_error: str | None
    last_push_attempt_at: datetime | None
    last_pull_attempt_at: datetime | None
    synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WallabagSyncJob:
    job_key: str
    bucket_item_id: str
    job_type: str
    run_after: datetime
    attempt_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WallabagAuthState:
    access_token: str
    refresh_token: str | None
    token_type: str
    expires_at: datetime
    updated_at: datetime


class ArticleWallabagRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_article_state(self, *, bucket_item_id: str) -> ArticleWallabagState | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT
                    bucket_item_id,
                    source_url,
                    canonical_url,
                    sync_status,
                    wallabag_entry_id,
                    wallabag_entry_url,
                    read_state,
                    read_at,
                    sync_error,
                    last_push_attempt_at,
                    last_pull_attempt_at,
                    synced_at,
                    created_at,
                    updated_at
                FROM article_wallabag_state
                WHERE bucket_item_id = ?
                LIMIT 1
                """,
                (bucket_item_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_article_state(row)

    def ensure_article_state(
        self,
        *,
        bucket_item_id: str,
        source_url: str,
        canonical_url: str | None,
        default_sync_status: str,
    ) -> ArticleWallabagState:
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO article_wallabag_state (
                    bucket_item_id,
                    source_url,
                    canonical_url,
                    sync_status,
                    wallabag_entry_id,
                    wallabag_entry_url,
                    read_state,
                    read_at,
                    sync_error,
                    last_push_attempt_at,
                    last_pull_attempt_at,
                    synced_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, ?, ?)
                ON CONFLICT(bucket_item_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    canonical_url = COALESCE(excluded.canonical_url, article_wallabag_state.canonical_url),
                    updated_at = excluded.updated_at
                """,
                (
                    bucket_item_id,
                    source_url,
                    canonical_url,
                    default_sync_status,
                    READ_STATE_UNREAD,
                    now_iso,
                    now_iso,
                ),
            )

        state = self.get_article_state(bucket_item_id=bucket_item_id)
        if state is None:
            raise RuntimeError("article_wallabag_state missing after ensure")
        return state

    def update_sync_state(
        self,
        *,
        bucket_item_id: str,
        sync_status: str,
        sync_error: str | None,
        wallabag_entry_id: int | None = None,
        wallabag_entry_url: str | None = None,
        synced_at: datetime | None = None,
        last_push_attempt_at: datetime | None = None,
        last_pull_attempt_at: datetime | None = None,
    ) -> ArticleWallabagState | None:
        existing = self.get_article_state(bucket_item_id=bucket_item_id)
        if existing is None:
            return None

        next_entry_id = (
            wallabag_entry_id if wallabag_entry_id is not None else existing.wallabag_entry_id
        )
        next_entry_url = (
            wallabag_entry_url if wallabag_entry_url is not None else existing.wallabag_entry_url
        )
        next_synced_at = synced_at if synced_at is not None else existing.synced_at
        next_push_attempt_at = (
            last_push_attempt_at
            if last_push_attempt_at is not None
            else existing.last_push_attempt_at
        )
        next_pull_attempt_at = (
            last_pull_attempt_at
            if last_pull_attempt_at is not None
            else existing.last_pull_attempt_at
        )

        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE article_wallabag_state
                SET
                    sync_status = ?,
                    sync_error = ?,
                    wallabag_entry_id = ?,
                    wallabag_entry_url = ?,
                    synced_at = ?,
                    last_push_attempt_at = ?,
                    last_pull_attempt_at = ?,
                    updated_at = ?
                WHERE bucket_item_id = ?
                """,
                (
                    sync_status,
                    _trim_optional_text(sync_error, max_len=1000),
                    next_entry_id,
                    _trim_optional_text(next_entry_url, max_len=2000),
                    _datetime_to_iso_or_none(next_synced_at),
                    _datetime_to_iso_or_none(next_push_attempt_at),
                    _datetime_to_iso_or_none(next_pull_attempt_at),
                    utc_now_iso(),
                    bucket_item_id,
                ),
            )
        return self.get_article_state(bucket_item_id=bucket_item_id)

    def update_read_state(
        self,
        *,
        bucket_item_id: str,
        read_state: str,
        read_at: datetime | None,
    ) -> ArticleWallabagState | None:
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE article_wallabag_state
                SET
                    read_state = ?,
                    read_at = ?,
                    updated_at = ?
                WHERE bucket_item_id = ?
                """,
                (
                    read_state,
                    _datetime_to_iso_or_none(read_at),
                    utc_now_iso(),
                    bucket_item_id,
                ),
            )
            if cursor.rowcount <= 0:
                return None
        return self.get_article_state(bucket_item_id=bucket_item_id)

    def upsert_sync_job(
        self,
        *,
        bucket_item_id: str,
        job_type: str,
        run_after: datetime,
        reset_attempt_count: bool,
        last_error: str | None = None,
    ) -> WallabagSyncJob:
        now_iso = utc_now_iso()
        job_key = _build_job_key(bucket_item_id=bucket_item_id, job_type=job_type)
        reset_flag = 1 if reset_attempt_count else 0
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO wallabag_sync_jobs (
                    job_key,
                    bucket_item_id,
                    job_type,
                    run_after,
                    attempt_count,
                    last_error,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(job_key) DO UPDATE SET
                    run_after = excluded.run_after,
                    last_error = excluded.last_error,
                    attempt_count = CASE
                        WHEN ? = 1 THEN 0
                        ELSE wallabag_sync_jobs.attempt_count
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    job_key,
                    bucket_item_id,
                    job_type,
                    run_after.astimezone(UTC).isoformat(),
                    _trim_optional_text(last_error, max_len=1000),
                    now_iso,
                    now_iso,
                    reset_flag,
                ),
            )

        job = self.get_sync_job(job_key=job_key)
        if job is None:
            raise RuntimeError("wallabag_sync_jobs missing after upsert")
        return job

    def get_sync_job(self, *, job_key: str) -> WallabagSyncJob | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT
                    job_key,
                    bucket_item_id,
                    job_type,
                    run_after,
                    attempt_count,
                    last_error,
                    created_at,
                    updated_at
                FROM wallabag_sync_jobs
                WHERE job_key = ?
                LIMIT 1
                """,
                (job_key,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_sync_job(row)

    def list_due_sync_jobs(self, *, now: datetime, limit: int) -> list[WallabagSyncJob]:
        requested_limit = max(1, limit)
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    job_key,
                    bucket_item_id,
                    job_type,
                    run_after,
                    attempt_count,
                    last_error,
                    created_at,
                    updated_at
                FROM wallabag_sync_jobs
                WHERE run_after <= ?
                ORDER BY run_after ASC
                LIMIT ?
                """,
                (now.astimezone(UTC).isoformat(), requested_limit),
            ).fetchall()
        return [_row_to_sync_job(row) for row in rows]

    def update_sync_job_retry(
        self,
        *,
        job_key: str,
        run_after: datetime,
        attempt_count: int,
        last_error: str,
    ) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE wallabag_sync_jobs
                SET
                    run_after = ?,
                    attempt_count = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE job_key = ?
                """,
                (
                    run_after.astimezone(UTC).isoformat(),
                    max(1, attempt_count),
                    _trim_optional_text(last_error, max_len=1000),
                    utc_now_iso(),
                    job_key,
                ),
            )

    def delete_sync_job(self, *, job_key: str) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM wallabag_sync_jobs WHERE job_key = ?",
                (job_key,),
            )

    def get_auth_state(self) -> WallabagAuthState | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT access_token, refresh_token, token_type, expires_at, updated_at
                FROM wallabag_auth_state
                WHERE singleton_id = 1
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None

        expires_at = _parse_datetime_or_none(row["expires_at"])
        updated_at = _parse_datetime_or_none(row["updated_at"])
        access_token = _to_optional_text(row["access_token"])
        token_type = _to_optional_text(row["token_type"])
        if access_token is None or token_type is None or expires_at is None or updated_at is None:
            return None

        return WallabagAuthState(
            access_token=access_token,
            refresh_token=_to_optional_text(row["refresh_token"]),
            token_type=token_type,
            expires_at=expires_at,
            updated_at=updated_at,
        )

    def upsert_auth_state(
        self,
        *,
        access_token: str,
        refresh_token: str | None,
        token_type: str,
        expires_at: datetime,
    ) -> WallabagAuthState:
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO wallabag_auth_state (
                    singleton_id,
                    access_token,
                    refresh_token,
                    token_type,
                    expires_at,
                    updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    token_type = excluded.token_type,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    access_token,
                    _trim_optional_text(refresh_token, max_len=4096),
                    token_type,
                    expires_at.astimezone(UTC).isoformat(),
                    now_iso,
                ),
            )

        state = self.get_auth_state()
        if state is None:
            raise RuntimeError("wallabag_auth_state missing after upsert")
        return state


def _build_job_key(*, bucket_item_id: str, job_type: str) -> str:
    return f"{bucket_item_id}:{job_type}"


def _row_to_article_state(row: Row) -> ArticleWallabagState:
    created_at = _parse_datetime_or_none(row["created_at"])
    updated_at = _parse_datetime_or_none(row["updated_at"])
    if created_at is None or updated_at is None:
        raise RuntimeError("article_wallabag_state contains invalid timestamps")

    source_url = _to_optional_text(row["source_url"])
    sync_status = _to_optional_text(row["sync_status"])
    read_state = _to_optional_text(row["read_state"])
    if source_url is None or sync_status is None or read_state is None:
        raise RuntimeError("article_wallabag_state contains invalid required fields")

    return ArticleWallabagState(
        bucket_item_id=str(row["bucket_item_id"]),
        source_url=source_url,
        canonical_url=_to_optional_text(row["canonical_url"]),
        sync_status=sync_status,
        wallabag_entry_id=_to_optional_int(row["wallabag_entry_id"]),
        wallabag_entry_url=_to_optional_text(row["wallabag_entry_url"]),
        read_state=read_state,
        read_at=_parse_datetime_or_none(row["read_at"]),
        sync_error=_to_optional_text(row["sync_error"]),
        last_push_attempt_at=_parse_datetime_or_none(row["last_push_attempt_at"]),
        last_pull_attempt_at=_parse_datetime_or_none(row["last_pull_attempt_at"]),
        synced_at=_parse_datetime_or_none(row["synced_at"]),
        created_at=created_at,
        updated_at=updated_at,
    )


def _row_to_sync_job(row: Row) -> WallabagSyncJob:
    run_after = _parse_datetime_or_none(row["run_after"])
    created_at = _parse_datetime_or_none(row["created_at"])
    updated_at = _parse_datetime_or_none(row["updated_at"])
    if run_after is None or created_at is None or updated_at is None:
        raise RuntimeError("wallabag_sync_jobs contains invalid timestamps")

    return WallabagSyncJob(
        job_key=str(row["job_key"]),
        bucket_item_id=str(row["bucket_item_id"]),
        job_type=str(row["job_type"]),
        run_after=run_after,
        attempt_count=max(0, _to_optional_int(row["attempt_count"]) or 0),
        last_error=_to_optional_text(row["last_error"]),
        created_at=created_at,
        updated_at=updated_at,
    )


def _parse_datetime_or_none(value: object) -> datetime | None:
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _to_optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _to_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _datetime_to_iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def _trim_optional_text(value: str | None, *, max_len: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:max_len]
