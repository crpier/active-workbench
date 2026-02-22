from __future__ import annotations

import errno
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from structlog.contextvars import bind_contextvars, reset_contextvars

from backend.app.services.tool_dispatcher import ToolDispatcher
from backend.app.services.youtube_service import YouTubeService
from backend.app.telemetry import TelemetryClient

LOGGER = logging.getLogger("active_workbench.scheduler")
BUCKET_ANNOTATION_POLL_INTERVAL_SECONDS = 300

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


class SchedulerService:
    def __init__(
        self,
        dispatcher: ToolDispatcher,
        poll_interval_seconds: int,
        *,
        transcript_poll_interval_seconds: int | None = None,
        youtube_service: YouTubeService | None = None,
        telemetry: TelemetryClient | None = None,
        lock_path: Path | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._poll_interval_seconds = max(1, poll_interval_seconds)
        transcript_interval = (
            poll_interval_seconds
            if transcript_poll_interval_seconds is None
            else transcript_poll_interval_seconds
        )
        self._transcript_poll_interval_seconds = max(1, transcript_interval)
        self._youtube_service = youtube_service
        self._telemetry = telemetry if telemetry is not None else TelemetryClient.disabled()
        self._next_bucket_annotation_tick = 0.0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock_path = lock_path
        self._lock_file: Any | None = None
        self._lock_acquired = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        if not self._try_acquire_process_lock():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="active-workbench-scheduler")
        self._thread.daemon = True
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        self._release_process_lock()

    def _try_acquire_process_lock(self) -> bool:
        if self._lock_path is None:
            return True

        if fcntl is None:
            LOGGER.warning(
                "scheduler single-instance lock unavailable on this platform; starting scheduler"
            )
            return True

        lock_path = self._lock_path
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = lock_path.open("a+", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if "lock_file" in locals():
                try:
                    lock_file.close()
                except OSError:
                    pass
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                LOGGER.info(
                    "scheduler start skipped; lock held by another process path=%s",
                    lock_path,
                )
                return False
            LOGGER.warning(
                "scheduler lock acquisition failed path=%s; starting scheduler anyway",
                lock_path,
                exc_info=True,
            )
            return True

        try:
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(f"{os.getpid()}\n")
            lock_file.flush()
        except OSError:
            LOGGER.debug("scheduler lock file metadata write failed path=%s", lock_path, exc_info=True)

        self._lock_file = lock_file
        self._lock_acquired = True
        return True

    def _release_process_lock(self) -> None:
        lock_file = self._lock_file
        if lock_file is None:
            self._lock_acquired = False
            return

        try:
            if self._lock_acquired and fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except OSError:
            LOGGER.debug("scheduler lock release failed path=%s", self._lock_path, exc_info=True)
        finally:
            try:
                lock_file.close()
            except OSError:
                pass
            self._lock_file = None
            self._lock_acquired = False

    def _run_loop(self) -> None:
        next_scheduler_tick = 0.0
        next_transcript_tick = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now >= next_scheduler_tick:
                self._run_scheduler_tick()
                next_scheduler_tick = now + self._poll_interval_seconds

            if self._youtube_service is not None and now >= next_transcript_tick:
                self._run_transcript_tick()
                next_transcript_tick = now + self._transcript_poll_interval_seconds

            sleep_for_seconds = next_scheduler_tick - now
            if self._youtube_service is not None:
                sleep_for_seconds = min(sleep_for_seconds, next_transcript_tick - now)
            self._stop_event.wait(max(0.0, sleep_for_seconds))
            time.sleep(0)

    def _run_scheduler_tick(self) -> None:
        tick_id = uuid4().hex
        tick_tokens = bind_contextvars(scheduler_tick_id=tick_id, scheduler_tick_type="jobs")
        started_at = time.perf_counter()
        self._telemetry.emit(
            "scheduler.tick.start",
            tick_id=tick_id,
            tick_type="jobs",
        )
        try:
            self._dispatcher.run_due_jobs()
            now = time.monotonic()
            if now >= self._next_bucket_annotation_tick:
                self._run_bucket_annotation_tick()
                self._next_bucket_annotation_tick = now + BUCKET_ANNOTATION_POLL_INTERVAL_SECONDS

            if self._youtube_service is not None:
                sync_started = time.perf_counter()
                self._telemetry.emit(
                    "youtube.likes.background_sync.start",
                    tick_id=tick_id,
                )
                try:
                    self._youtube_service.run_background_likes_sync()
                except Exception as exc:
                    self._telemetry.emit(
                        "youtube.likes.background_sync.error",
                        tick_id=tick_id,
                        duration_ms=int((time.perf_counter() - sync_started) * 1000),
                        error_type=type(exc).__name__,
                    )
                    LOGGER.warning("youtube likes background sync failed", exc_info=True)
                else:
                    self._telemetry.emit(
                        "youtube.likes.background_sync.finish",
                        tick_id=tick_id,
                        duration_ms=int((time.perf_counter() - sync_started) * 1000),
                        outcome="ok",
                    )
            self._telemetry.emit(
                "scheduler.tick.finish",
                tick_id=tick_id,
                tick_type="jobs",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                outcome="ok",
            )
        except Exception as exc:
            self._telemetry.emit(
                "scheduler.tick.error",
                tick_id=tick_id,
                tick_type="jobs",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                error_type=type(exc).__name__,
            )
            raise
        finally:
            reset_contextvars(**tick_tokens)

    def _run_bucket_annotation_tick(self) -> None:
        run_poll = getattr(self._dispatcher, "run_bucket_annotation_poll", None)
        if not callable(run_poll):
            return

        tick_id = uuid4().hex
        started_at = time.perf_counter()
        self._telemetry.emit(
            "bucket.annotation.poll.start",
            tick_id=tick_id,
        )
        try:
            raw_result = run_poll()
            result: dict[str, Any] = (
                cast(dict[str, Any], raw_result) if isinstance(raw_result, dict) else {}
            )
            self._telemetry.emit(
                "bucket.annotation.poll.finish",
                tick_id=tick_id,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                **result,
            )
        except Exception as exc:
            self._telemetry.emit(
                "bucket.annotation.poll.error",
                tick_id=tick_id,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                error_type=type(exc).__name__,
            )
            LOGGER.warning("bucket annotation poll failed", exc_info=True)

    def _run_transcript_tick(self) -> None:
        if self._youtube_service is None:
            return

        tick_id = uuid4().hex
        tick_tokens = bind_contextvars(scheduler_tick_id=tick_id, scheduler_tick_type="transcripts")
        started_at = time.perf_counter()
        self._telemetry.emit(
            "scheduler.tick.start",
            tick_id=tick_id,
            tick_type="transcripts",
        )
        try:
            self._telemetry.emit(
                "youtube.transcript.background_sync.start",
                tick_id=tick_id,
            )
            sync_started = time.perf_counter()
            try:
                self._youtube_service.run_background_transcript_sync()
            except Exception as exc:
                self._telemetry.emit(
                    "youtube.transcript.background_sync.error",
                    tick_id=tick_id,
                    duration_ms=int((time.perf_counter() - sync_started) * 1000),
                    error_type=type(exc).__name__,
                )
                LOGGER.warning(
                    "youtube transcript background sync failed",
                    exc_info=True,
                )
            else:
                self._telemetry.emit(
                    "youtube.transcript.background_sync.finish",
                    tick_id=tick_id,
                    duration_ms=int((time.perf_counter() - sync_started) * 1000),
                    outcome="ok",
                )

            self._telemetry.emit(
                "scheduler.tick.finish",
                tick_id=tick_id,
                tick_type="transcripts",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                outcome="ok",
            )
        finally:
            reset_contextvars(**tick_tokens)
