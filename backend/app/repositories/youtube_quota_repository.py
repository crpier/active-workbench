from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database


@dataclass(frozen=True)
class YouTubeQuotaSnapshot:
    date_utc: str
    estimated_units_this_call: int
    estimated_units_today: int
    estimated_calls_today: int
    daily_limit: int
    warning_threshold: int
    warning: bool


class YouTubeQuotaRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record_and_snapshot(
        self,
        *,
        tool_name: str,
        estimated_units_this_call: int,
        daily_limit: int,
        warning_threshold: int,
    ) -> YouTubeQuotaSnapshot:
        date_utc = datetime.now(UTC).date().isoformat()
        units_this_call = max(0, estimated_units_this_call)

        with self._db.connection() as conn:
            if units_this_call > 0:
                now_iso = utc_now_iso()
                conn.execute(
                    """
                    INSERT INTO youtube_quota_daily (date_utc, units_used, calls, updated_at)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(date_utc) DO UPDATE SET
                        units_used = youtube_quota_daily.units_used + excluded.units_used,
                        calls = youtube_quota_daily.calls + 1,
                        updated_at = excluded.updated_at
                    """,
                    (date_utc, units_this_call, now_iso),
                )
                conn.execute(
                    """
                    INSERT INTO youtube_quota_by_tool_daily
                    (date_utc, tool_name, units_used, calls, updated_at)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(date_utc, tool_name) DO UPDATE SET
                        units_used = youtube_quota_by_tool_daily.units_used + excluded.units_used,
                        calls = youtube_quota_by_tool_daily.calls + 1,
                        updated_at = excluded.updated_at
                    """,
                    (date_utc, tool_name, units_this_call, now_iso),
                )

            daily_row = conn.execute(
                """
                SELECT units_used, calls
                FROM youtube_quota_daily
                WHERE date_utc = ?
                """,
                (date_utc,),
            ).fetchone()

        estimated_units_today = int(daily_row["units_used"]) if daily_row is not None else 0
        estimated_calls_today = int(daily_row["calls"]) if daily_row is not None else 0

        warning = daily_limit > 0 and estimated_units_today >= warning_threshold
        return YouTubeQuotaSnapshot(
            date_utc=date_utc,
            estimated_units_this_call=units_this_call,
            estimated_units_today=estimated_units_today,
            estimated_calls_today=estimated_calls_today,
            daily_limit=daily_limit,
            warning_threshold=warning_threshold,
            warning=warning,
        )
