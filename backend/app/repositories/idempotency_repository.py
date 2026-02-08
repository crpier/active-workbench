from __future__ import annotations

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database


class IdempotencyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_response_json(self, tool_name: str, idempotency_key: str) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT response_json
                FROM idempotency_records
                WHERE tool_name = ? AND idempotency_key = ?
                """,
                (tool_name, idempotency_key),
            ).fetchone()

        if row is None:
            return None
        return str(row["response_json"])

    def store_response_json(self, tool_name: str, idempotency_key: str, response_json: str) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO idempotency_records
                (tool_name, idempotency_key, response_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (tool_name, idempotency_key, response_json, utc_now_iso()),
            )
