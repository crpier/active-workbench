from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create_event(
        self,
        request_id: UUID,
        tool_name: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        event_id = f"evt_{uuid4().hex}"
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_events
                (id, request_id, tool_name, payload_json, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    str(request_id),
                    tool_name,
                    json.dumps(payload, sort_keys=True),
                    json.dumps(result, sort_keys=True),
                    utc_now_iso(),
                ),
            )
        return event_id
