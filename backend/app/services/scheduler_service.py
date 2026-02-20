from __future__ import annotations

import logging
import threading
import time

from backend.app.services.tool_dispatcher import ToolDispatcher
from backend.app.services.youtube_service import YouTubeService

LOGGER = logging.getLogger("active_workbench.scheduler")


class SchedulerService:
    def __init__(
        self,
        dispatcher: ToolDispatcher,
        poll_interval_seconds: int,
        *,
        transcript_poll_interval_seconds: int | None = None,
        youtube_service: YouTubeService | None = None,
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
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
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

    def _run_loop(self) -> None:
        next_scheduler_tick = 0.0
        next_transcript_tick = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now >= next_scheduler_tick:
                self._dispatcher.run_due_jobs()
                if self._youtube_service is not None:
                    try:
                        self._youtube_service.run_background_likes_sync()
                    except Exception:
                        LOGGER.warning("youtube likes background sync failed", exc_info=True)
                next_scheduler_tick = now + self._poll_interval_seconds

            if self._youtube_service is not None and now >= next_transcript_tick:
                try:
                    self._youtube_service.run_background_transcript_sync()
                except Exception:
                    LOGGER.warning(
                        "youtube transcript background sync failed",
                        exc_info=True,
                    )
                next_transcript_tick = now + self._transcript_poll_interval_seconds

            sleep_for_seconds = next_scheduler_tick - now
            if self._youtube_service is not None:
                sleep_for_seconds = min(sleep_for_seconds, next_transcript_tick - now)
            self._stop_event.wait(max(0.0, sleep_for_seconds))
            time.sleep(0)
