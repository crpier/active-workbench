from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database


@dataclass(frozen=True)
class ScheduledJob:
    job_id: str
    job_type: str
    run_at: datetime
    timezone: str
    payload: dict[str, Any]
    recurrence: str | None


class JobsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def schedule_job(
        self,
        *,
        job_type: str,
        run_at: datetime,
        timezone: str,
        payload: dict[str, Any],
        recurrence: str | None = None,
    ) -> str:
        job_id = f"job_{uuid4().hex}"
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs
                (id, job_type, run_at, timezone, payload_json, status, recurrence, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job_type,
                    run_at.astimezone(UTC).isoformat(),
                    timezone,
                    json.dumps(payload, sort_keys=True),
                    "scheduled",
                    recurrence,
                    utc_now_iso(),
                ),
            )
        return job_id

    def schedule_reminder(self, run_at: datetime, timezone: str, payload: dict[str, Any]) -> str:
        return self.schedule_job(
            job_type="reminder",
            run_at=run_at,
            timezone=timezone,
            payload=payload,
            recurrence=None,
        )

    def ensure_weekly_routine_review(self, run_at: datetime, timezone: str) -> str:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM jobs
                WHERE job_type = 'routine_review' AND recurrence = 'weekly' AND status = 'scheduled'
                LIMIT 1
                """
            ).fetchone()

            if row is not None:
                return str(row["id"])

        return self.schedule_job(
            job_type="routine_review",
            run_at=run_at,
            timezone=timezone,
            payload={"auto": True},
            recurrence="weekly",
        )

    def list_due_jobs(self, now_utc: datetime, limit: int = 20) -> list[ScheduledJob]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, job_type, run_at, timezone, payload_json, recurrence
                FROM jobs
                WHERE status = 'scheduled' AND run_at <= ?
                ORDER BY run_at ASC
                LIMIT ?
                """,
                (now_utc.astimezone(UTC).isoformat(), limit),
            ).fetchall()

        jobs: list[ScheduledJob] = []
        for row in rows:
            run_at = _parse_iso_datetime(str(row["run_at"]))
            payload = _load_payload(str(row["payload_json"]))
            jobs.append(
                ScheduledJob(
                    job_id=str(row["id"]),
                    job_type=str(row["job_type"]),
                    run_at=run_at,
                    timezone=str(row["timezone"]),
                    payload=payload,
                    recurrence=_none_if_empty(row["recurrence"]),
                )
            )
        return jobs

    def mark_completed(self, job_id: str, result: dict[str, Any]) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'completed', completed_at = ?, result_json = ?, last_run_at = ?
                WHERE id = ?
                """,
                (
                    utc_now_iso(),
                    json.dumps(result, sort_keys=True),
                    utc_now_iso(),
                    job_id,
                ),
            )

    def reschedule_weekly(self, job_id: str, next_run_at: datetime) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET run_at = ?, last_run_at = ?, status = 'scheduled',
                    completed_at = NULL, result_json = NULL
                WHERE id = ?
                """,
                (
                    next_run_at.astimezone(UTC).isoformat(),
                    utc_now_iso(),
                    job_id,
                ),
            )

    def list_upcoming_reminder_items(self, limit: int = 5) -> list[str]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM jobs
                WHERE job_type = 'reminder' AND status = 'scheduled'
                ORDER BY run_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        items: list[str] = []
        for row in rows:
            payload = _load_payload(str(row["payload_json"]))
            for key in ("item", "ingredient", "name", "title"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    items.append(value.strip())
                    break
        return items


def _load_payload(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    if isinstance(parsed, dict):
        raw_dict = cast(dict[object, object], parsed)
        payload: dict[str, Any] = {}
        for key, value in raw_dict.items():
            if isinstance(key, str):
                payload[key] = value
        return payload
    return {}


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _none_if_empty(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
