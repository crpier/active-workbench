from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database


@dataclass(frozen=True)
class BucketBookwyrmQuotaSnapshot:
    date_utc: str
    daily_soft_limit: int
    calls_today: int
    allowed: bool
    daily_limited: bool
    burst_limited: bool
    retry_after_seconds: float | None


class BucketBookwyrmQuotaRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def try_consume_call(
        self,
        *,
        daily_soft_limit: int,
        min_interval_seconds: float,
    ) -> BucketBookwyrmQuotaSnapshot:
        date_utc = datetime.now(UTC).date().isoformat()
        soft_limit = max(0, daily_soft_limit)
        min_interval = max(0.0, min_interval_seconds)
        now = datetime.now(UTC)
        now_iso = utc_now_iso()

        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT calls, updated_at
                FROM bucket_bookwyrm_quota_daily
                WHERE date_utc = ?
                """,
                (date_utc,),
            ).fetchone()

            calls_today = int(row["calls"]) if row is not None else 0
            last_updated_at = _parse_iso_utc(str(row["updated_at"])) if row is not None else None
            retry_after_seconds: float | None = None

            if min_interval > 0 and calls_today > 0 and last_updated_at is not None:
                elapsed_seconds = max(0.0, (now - last_updated_at).total_seconds())
                if elapsed_seconds < min_interval:
                    retry_after_seconds = round(min_interval - elapsed_seconds, 3)
                    return BucketBookwyrmQuotaSnapshot(
                        date_utc=date_utc,
                        daily_soft_limit=soft_limit,
                        calls_today=calls_today,
                        allowed=False,
                        daily_limited=False,
                        burst_limited=True,
                        retry_after_seconds=retry_after_seconds,
                    )

            if soft_limit > 0 and calls_today >= soft_limit:
                return BucketBookwyrmQuotaSnapshot(
                    date_utc=date_utc,
                    daily_soft_limit=soft_limit,
                    calls_today=calls_today,
                    allowed=False,
                    daily_limited=True,
                    burst_limited=False,
                    retry_after_seconds=None,
                )

            if row is None:
                conn.execute(
                    """
                    INSERT INTO bucket_bookwyrm_quota_daily (date_utc, calls, updated_at)
                    VALUES (?, 1, ?)
                    """,
                    (date_utc, now_iso),
                )
                calls_today = 1
            else:
                conn.execute(
                    """
                    UPDATE bucket_bookwyrm_quota_daily
                    SET calls = calls + 1, updated_at = ?
                    WHERE date_utc = ?
                    """,
                    (now_iso, date_utc),
                )
                calls_today += 1

        return BucketBookwyrmQuotaSnapshot(
            date_utc=date_utc,
            daily_soft_limit=soft_limit,
            calls_today=calls_today,
            allowed=True,
            daily_limited=False,
            burst_limited=False,
            retry_after_seconds=None,
        )


def _parse_iso_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
