from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database


class JobsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def schedule_reminder(self, run_at: datetime, timezone: str, payload: dict[str, object]) -> str:
        job_id = f"job_{uuid4().hex}"
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, job_type, run_at, timezone, payload_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    "reminder",
                    run_at.isoformat(),
                    timezone,
                    json.dumps(payload, sort_keys=True),
                    "scheduled",
                    utc_now_iso(),
                ),
            )
        return job_id

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
            payload = json.loads(str(row["payload_json"]))
            for key in ("item", "ingredient", "name", "title"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    items.append(value.strip())
                    break
        return items
