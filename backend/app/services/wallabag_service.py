from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.app.repositories.article_wallabag_repository import (
    JOB_TYPE_PULL,
    JOB_TYPE_PUSH,
    READ_STATE_READ,
    READ_STATE_UNREAD,
    SYNC_STATUS_FAILED,
    SYNC_STATUS_PENDING,
    SYNC_STATUS_SYNCED,
    ArticleWallabagRepository,
    ArticleWallabagState,
    WallabagAuthState,
    WallabagSyncJob,
)
from backend.app.repositories.bucket_repository import BucketRepository
from backend.app.telemetry import TelemetryClient

LOGGER = logging.getLogger("active_workbench.wallabag")


@dataclass(frozen=True)
class WallabagSyncStats:
    processed: int
    succeeded: int
    failed: int
    retried: int


class WallabagApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None, retryable: bool) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class WallabagService:
    def __init__(
        self,
        *,
        enabled: bool,
        base_url: str | None,
        client_id: str | None,
        client_secret: str | None,
        username: str | None,
        password: str | None,
        http_timeout_seconds: float,
        job_batch_size: int,
        retry_base_seconds: int,
        retry_max_seconds: int,
        article_repository: ArticleWallabagRepository,
        bucket_repository: BucketRepository,
        telemetry: TelemetryClient | None = None,
    ) -> None:
        if not enabled:
            raise ValueError("WallabagService requires enabled=True.")
        self._base_url = base_url.rstrip("/") if isinstance(base_url, str) else None
        self._client_id = client_id
        self._client_secret = client_secret
        self._username = username
        self._password = password
        self._http_timeout_seconds = max(1.0, float(http_timeout_seconds))
        self._job_batch_size = max(1, int(job_batch_size))
        self._retry_base_seconds = max(1, int(retry_base_seconds))
        self._retry_max_seconds = max(self._retry_base_seconds, int(retry_max_seconds))
        self._article_repository = article_repository
        self._bucket_repository = bucket_repository
        self._telemetry = telemetry if telemetry is not None else TelemetryClient.disabled()

    def track_article_capture(
        self,
        *,
        bucket_item_id: str,
        source_url: str,
        canonical_url: str | None,
        eager_sync: bool,
    ) -> ArticleWallabagState:
        state = self._article_repository.ensure_article_state(
            bucket_item_id=bucket_item_id,
            source_url=source_url,
            canonical_url=canonical_url,
            default_sync_status=SYNC_STATUS_PENDING,
        )

        if state.wallabag_entry_id is None:
            self._article_repository.update_sync_state(
                bucket_item_id=bucket_item_id,
                sync_status=SYNC_STATUS_PENDING,
                sync_error=None,
            )
            self._article_repository.upsert_sync_job(
                bucket_item_id=bucket_item_id,
                job_type=JOB_TYPE_PUSH,
                run_after=datetime.now(UTC),
                reset_attempt_count=False,
                last_error=None,
            )
            if eager_sync:
                self.process_due_jobs(limit=1)
            refreshed = self._article_repository.get_article_state(bucket_item_id=bucket_item_id)
            if refreshed is not None:
                return refreshed
        return state

    def get_sync_status(self, *, bucket_item_id: str) -> ArticleWallabagState | None:
        existing = self._article_repository.get_article_state(bucket_item_id=bucket_item_id)
        if existing is not None:
            return existing

        item = self._bucket_repository.get_item(bucket_item_id)
        if item is None or item.domain != "article":
            return None
        if item.external_url is None:
            return None
        return self.track_article_capture(
            bucket_item_id=bucket_item_id,
            source_url=item.external_url,
            canonical_url=item.external_url,
            eager_sync=False,
        )

    def refresh_article(self, *, bucket_item_id: str) -> ArticleWallabagState | None:
        state = self.get_sync_status(bucket_item_id=bucket_item_id)
        if state is None:
            return None

        job_type = JOB_TYPE_PULL if state.wallabag_entry_id is not None else JOB_TYPE_PUSH
        self._article_repository.upsert_sync_job(
            bucket_item_id=bucket_item_id,
            job_type=job_type,
            run_after=datetime.now(UTC),
            reset_attempt_count=True,
            last_error=None,
        )
        self._article_repository.update_sync_state(
            bucket_item_id=bucket_item_id,
            sync_status=SYNC_STATUS_PENDING,
            sync_error=None,
        )
        self.process_due_jobs(limit=1)
        return self._article_repository.get_article_state(bucket_item_id=bucket_item_id)

    def set_read_state(self, *, bucket_item_id: str, read: bool) -> ArticleWallabagState | None:
        if self.get_sync_status(bucket_item_id=bucket_item_id) is None:
            return None

        read_state = READ_STATE_READ if read else READ_STATE_UNREAD
        read_at = datetime.now(UTC) if read else None
        state = self._article_repository.update_read_state(
            bucket_item_id=bucket_item_id,
            read_state=read_state,
            read_at=read_at,
        )
        if state is None:
            return None

        if state.wallabag_entry_id is None:
            self._article_repository.upsert_sync_job(
                bucket_item_id=bucket_item_id,
                job_type=JOB_TYPE_PUSH,
                run_after=datetime.now(UTC),
                reset_attempt_count=False,
                last_error=None,
            )
            self._article_repository.update_sync_state(
                bucket_item_id=bucket_item_id,
                sync_status=SYNC_STATUS_PENDING,
                sync_error=None,
            )
            return self._article_repository.get_article_state(bucket_item_id=bucket_item_id)

        now = datetime.now(UTC)
        try:
            self._set_remote_archive_status(
                entry_id=state.wallabag_entry_id,
                archived=read,
            )
        except WallabagApiError as exc:
            LOGGER.warning("wallabag read-state sync failed", exc_info=True)
            self._article_repository.upsert_sync_job(
                bucket_item_id=bucket_item_id,
                job_type=JOB_TYPE_PULL,
                run_after=now,
                reset_attempt_count=False,
                last_error=str(exc),
            )
            self._article_repository.update_sync_state(
                bucket_item_id=bucket_item_id,
                sync_status=SYNC_STATUS_FAILED,
                sync_error=str(exc),
                last_pull_attempt_at=now,
            )
            return self._article_repository.get_article_state(bucket_item_id=bucket_item_id)

        self._article_repository.update_sync_state(
            bucket_item_id=bucket_item_id,
            sync_status=SYNC_STATUS_SYNCED,
            sync_error=None,
            synced_at=now,
            last_pull_attempt_at=now,
        )
        return self._article_repository.get_article_state(bucket_item_id=bucket_item_id)

    def process_due_jobs(self, *, limit: int | None = None) -> WallabagSyncStats:
        effective_limit = self._job_batch_size if limit is None else max(1, int(limit))
        jobs = self._article_repository.list_due_sync_jobs(now=datetime.now(UTC), limit=effective_limit)

        processed = 0
        succeeded = 0
        failed = 0
        retried = 0

        for job in jobs:
            processed += 1
            try:
                self._process_job(job)
            except WallabagApiError as exc:
                failed += 1
                if exc.retryable:
                    retried += 1
                    next_attempt = self._next_retry_at(job.attempt_count + 1)
                    self._article_repository.update_sync_job_retry(
                        job_key=job.job_key,
                        run_after=next_attempt,
                        attempt_count=job.attempt_count + 1,
                        last_error=str(exc),
                    )
                else:
                    self._article_repository.delete_sync_job(job_key=job.job_key)

                self._article_repository.update_sync_state(
                    bucket_item_id=job.bucket_item_id,
                    sync_status=SYNC_STATUS_FAILED,
                    sync_error=str(exc),
                )
                LOGGER.warning(
                    "wallabag sync job failed job_key=%s retryable=%s status=%s",
                    job.job_key,
                    exc.retryable,
                    exc.status_code,
                )
            else:
                succeeded += 1
                self._article_repository.delete_sync_job(job_key=job.job_key)

        stats = WallabagSyncStats(
            processed=processed,
            succeeded=succeeded,
            failed=failed,
            retried=retried,
        )
        self._telemetry.emit(
            "wallabag.sync.jobs",
            processed=stats.processed,
            succeeded=stats.succeeded,
            failed=stats.failed,
            retried=stats.retried,
        )
        return stats

    def _process_job(self, job: WallabagSyncJob) -> None:
        if job.job_type == JOB_TYPE_PUSH:
            self._sync_push(job.bucket_item_id)
            return
        if job.job_type == JOB_TYPE_PULL:
            self._sync_pull(job.bucket_item_id)
            return
        raise WallabagApiError(
            f"Unsupported wallabag job type: {job.job_type}",
            status_code=None,
            retryable=False,
        )

    def _sync_push(self, bucket_item_id: str) -> None:
        state = self._article_repository.get_article_state(bucket_item_id=bucket_item_id)
        item = self._bucket_repository.get_item(bucket_item_id)
        if state is None or item is None:
            raise WallabagApiError(
                "Bucket item no longer exists for wallabag sync.",
                status_code=None,
                retryable=False,
            )

        now = datetime.now(UTC)
        article_url = state.canonical_url or state.source_url or item.external_url
        if article_url is None:
            raise WallabagApiError(
                "Article URL missing for wallabag capture.",
                status_code=None,
                retryable=False,
            )

        payload: dict[str, object] = {
            "url": article_url,
            "title": item.title,
            "archive": 1 if state.read_state == READ_STATE_READ else 0,
        }
        if item.notes.strip():
            payload["content"] = item.notes.strip()[:1000]

        response = self._api_request_json(
            method="POST",
            path="/api/entries.json",
            payload=payload,
        )

        entry_id = _to_optional_int(response.get("id"))
        if entry_id is None:
            raise WallabagApiError(
                "Wallabag create entry response missing id.",
                status_code=None,
                retryable=True,
            )

        remote_archived = _to_optional_bool(response.get("is_archived"))
        local_read_state = state.read_state
        if remote_archived is not None:
            local_read_state = READ_STATE_READ if remote_archived else READ_STATE_UNREAD

        self._article_repository.update_read_state(
            bucket_item_id=bucket_item_id,
            read_state=local_read_state,
            read_at=(now if local_read_state == READ_STATE_READ else None),
        )
        self._article_repository.update_sync_state(
            bucket_item_id=bucket_item_id,
            sync_status=SYNC_STATUS_SYNCED,
            sync_error=None,
            wallabag_entry_id=entry_id,
            wallabag_entry_url=_extract_entry_link(response),
            synced_at=now,
            last_push_attempt_at=now,
        )

    def _sync_pull(self, bucket_item_id: str) -> None:
        state = self._article_repository.get_article_state(bucket_item_id=bucket_item_id)
        if state is None or state.wallabag_entry_id is None:
            raise WallabagApiError(
                "Cannot refresh wallabag state before initial sync.",
                status_code=None,
                retryable=False,
            )

        now = datetime.now(UTC)
        response = self._api_request_json(
            method="GET",
            path=f"/api/entries/{state.wallabag_entry_id}.json",
            payload=None,
        )

        archived = _to_optional_bool(response.get("is_archived"))
        if archived is None:
            archived = state.read_state == READ_STATE_READ
        read_state = READ_STATE_READ if archived else READ_STATE_UNREAD

        self._article_repository.update_read_state(
            bucket_item_id=bucket_item_id,
            read_state=read_state,
            read_at=(now if read_state == READ_STATE_READ else None),
        )
        self._article_repository.update_sync_state(
            bucket_item_id=bucket_item_id,
            sync_status=SYNC_STATUS_SYNCED,
            sync_error=None,
            wallabag_entry_id=state.wallabag_entry_id,
            wallabag_entry_url=_extract_entry_link(response) or state.wallabag_entry_url,
            synced_at=now,
            last_pull_attempt_at=now,
        )

    def _set_remote_archive_status(self, *, entry_id: int, archived: bool) -> None:
        self._api_request_json(
            method="PATCH",
            path=f"/api/entries/{entry_id}.json",
            payload={"archive": 1 if archived else 0},
        )

    def _next_retry_at(self, attempt_count: int) -> datetime:
        exponent = max(0, attempt_count - 1)
        backoff_seconds = self._retry_base_seconds * (2**exponent)
        bounded = min(self._retry_max_seconds, backoff_seconds)
        return datetime.now(UTC) + timedelta(seconds=bounded)

    def _api_request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None,
    ) -> dict[str, object]:
        token = self._get_access_token(force_refresh=False)
        try:
            return self._request_json(
                method=method,
                path=path,
                payload=payload,
                access_token=token,
                form_encoded=False,
            )
        except WallabagApiError as exc:
            if exc.status_code != 401:
                raise

        refreshed_token = self._get_access_token(force_refresh=True)
        return self._request_json(
            method=method,
            path=path,
            payload=payload,
            access_token=refreshed_token,
            form_encoded=False,
        )

    def _get_access_token(self, *, force_refresh: bool) -> str:
        now = datetime.now(UTC)
        cached = self._article_repository.get_auth_state()
        if (
            not force_refresh
            and cached is not None
            and cached.expires_at > now + timedelta(seconds=15)
            and cached.access_token
        ):
            return cached.access_token

        if cached is not None and cached.refresh_token and not force_refresh:
            try:
                refreshed = self._request_json(
                    method="POST",
                    path="/oauth/v2/token",
                    payload={
                        "grant_type": "refresh_token",
                        "refresh_token": cached.refresh_token,
                        "client_id": self._client_id or "",
                        "client_secret": self._client_secret or "",
                    },
                    access_token=None,
                    form_encoded=True,
                )
                return self._store_auth_response(refreshed).access_token
            except WallabagApiError:
                LOGGER.info("wallabag refresh-token flow failed; falling back to password grant")

        created = self._request_json(
            method="POST",
            path="/oauth/v2/token",
            payload={
                "grant_type": "password",
                "client_id": self._client_id or "",
                "client_secret": self._client_secret or "",
                "username": self._username or "",
                "password": self._password or "",
            },
            access_token=None,
            form_encoded=True,
        )
        return self._store_auth_response(created).access_token

    def _store_auth_response(self, payload: dict[str, object]) -> WallabagAuthState:
        access_token = _to_optional_text(payload.get("access_token"))
        if access_token is None:
            raise WallabagApiError(
                "Wallabag OAuth response missing access token.",
                status_code=None,
                retryable=True,
            )

        expires_in = _to_optional_int(payload.get("expires_in"))
        expires_in_seconds = max(30, expires_in if expires_in is not None else 3600)
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)

        return self._article_repository.upsert_auth_state(
            access_token=access_token,
            refresh_token=_to_optional_text(payload.get("refresh_token")),
            token_type=_to_optional_text(payload.get("token_type")) or "bearer",
            expires_at=expires_at,
        )

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None,
        access_token: str | None,
        form_encoded: bool,
    ) -> dict[str, object]:
        if self._base_url is None:
            raise WallabagApiError(
                "Wallabag integration is not configured.",
                status_code=None,
                retryable=False,
            )
        url = f"{self._base_url}{path}"
        body: bytes | None = None
        headers: dict[str, str] = {"Accept": "application/json"}

        if payload is not None:
            if form_encoded:
                body = urlencode({key: str(value) for key, value in payload.items()}).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
                headers["Content-Type"] = "application/json"

        if access_token is not None:
            headers["Authorization"] = f"Bearer {access_token}"

        request = Request(
            url=url,
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(request, timeout=self._http_timeout_seconds) as response:
                raw_body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            parsed = _decode_json_object(response_body)
            message = _extract_error_message(parsed) or response_body or str(exc)
            raise WallabagApiError(
                f"Wallabag API request failed: {message}",
                status_code=exc.code,
                retryable=(exc.code >= 500 or exc.code in {408, 429}),
            ) from exc
        except URLError as exc:
            raise WallabagApiError(
                f"Wallabag request failed: {exc.reason}",
                status_code=None,
                retryable=True,
            ) from exc

        parsed = _decode_json_object(raw_body)
        return parsed


def _decode_json_object(raw_body: str) -> dict[str, object]:
    if not raw_body.strip():
        return {}
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        parsed_dict = cast(dict[object, object], parsed)
        output: dict[str, object] = {}
        for key, value in parsed_dict.items():
            if isinstance(key, str):
                output[key] = value
        return output
    return {}


def _extract_error_message(payload: dict[str, object]) -> str | None:
    for key in ("error_description", "message", "error"):
        value = _to_optional_text(payload.get(key))
        if value is not None:
            return value
    return None


def _extract_entry_link(payload: dict[str, object]) -> str | None:
    for key in ("given_url", "url"):
        value = _to_optional_text(payload.get(key))
        if value is not None:
            return value
    return None


def _to_optional_text(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
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
            return int(value.strip())
        except ValueError:
            return None
    return None


def _to_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None
