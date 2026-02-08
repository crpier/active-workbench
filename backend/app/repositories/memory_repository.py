from __future__ import annotations

import json
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
                    "content": json.loads(str(row["content_json"])),
                    "source_refs": json.loads(str(row["source_refs_json"])),
                    "created_at": str(row["created_at"]),
                }
            )
        return entries
