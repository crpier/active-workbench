from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from backend.app.repositories.common import utc_now_iso
from backend.app.repositories.database import Database


@dataclass(frozen=True)
class MobileApiKeyRecord:
    key_id: str
    device_name: str
    created_at: str
    revoked_at: str | None
    last_used_at: str | None
    last_seen_ip: str | None


class MobileApiKeyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create_key(self, device_name: str) -> tuple[MobileApiKeyRecord, str]:
        normalized_device_name = device_name.strip()
        if not normalized_device_name:
            raise ValueError("device_name must not be empty")

        key_id = f"mkey_{secrets.token_urlsafe(9)}"
        secret = secrets.token_urlsafe(24)
        now_iso = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO mobile_api_keys (
                    key_id, device_name, secret_hash, created_at,
                    revoked_at, last_used_at, last_seen_ip
                )
                VALUES (?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (
                    key_id,
                    normalized_device_name,
                    _hash_secret(secret),
                    now_iso,
                ),
            )
        return (
            MobileApiKeyRecord(
                key_id=key_id,
                device_name=normalized_device_name,
                created_at=now_iso,
                revoked_at=None,
                last_used_at=None,
                last_seen_ip=None,
            ),
            f"{key_id}.{secret}",
        )

    def has_active_keys(self) -> bool:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM mobile_api_keys
                WHERE revoked_at IS NULL
                LIMIT 1
                """
            ).fetchone()
        return row is not None

    def verify_active_token(self, *, key_id: str, secret: str) -> bool:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT secret_hash
                FROM mobile_api_keys
                WHERE key_id = ? AND revoked_at IS NULL
                """,
                (key_id,),
            ).fetchone()

        if row is None:
            return False
        stored_hash = str(row["secret_hash"])
        return secrets.compare_digest(stored_hash, _hash_secret(secret))

    def mark_used(self, *, key_id: str, client_ip: str) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE mobile_api_keys
                SET last_used_at = ?, last_seen_ip = ?
                WHERE key_id = ? AND revoked_at IS NULL
                """,
                (utc_now_iso(), client_ip, key_id),
            )

    def revoke_key(self, key_id: str) -> bool:
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE mobile_api_keys
                SET revoked_at = ?
                WHERE key_id = ? AND revoked_at IS NULL
                """,
                (utc_now_iso(), key_id.strip()),
            )
        return cursor.rowcount > 0

    def list_keys(self, *, include_revoked: bool) -> list[MobileApiKeyRecord]:
        query = """
            SELECT key_id, device_name, created_at, revoked_at, last_used_at, last_seen_ip
            FROM mobile_api_keys
        """
        params: tuple[object, ...] = ()
        if not include_revoked:
            query += " WHERE revoked_at IS NULL"
        query += " ORDER BY created_at DESC"

        with self._db.connection() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            MobileApiKeyRecord(
                key_id=str(row["key_id"]),
                device_name=str(row["device_name"]),
                created_at=str(row["created_at"]),
                revoked_at=(str(row["revoked_at"]) if row["revoked_at"] is not None else None),
                last_used_at=(
                    str(row["last_used_at"]) if row["last_used_at"] is not None else None
                ),
                last_seen_ip=(
                    str(row["last_seen_ip"]) if row["last_seen_ip"] is not None else None
                ),
            )
            for row in rows
        ]


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
