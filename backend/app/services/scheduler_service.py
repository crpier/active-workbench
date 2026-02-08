from __future__ import annotations

import threading
import time

from backend.app.services.tool_dispatcher import ToolDispatcher


class SchedulerService:
    def __init__(self, dispatcher: ToolDispatcher, poll_interval_seconds: int) -> None:
        self._dispatcher = dispatcher
        self._poll_interval_seconds = max(1, poll_interval_seconds)
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
        while not self._stop_event.is_set():
            self._dispatcher.run_due_jobs()
            self._stop_event.wait(self._poll_interval_seconds)
            time.sleep(0)
