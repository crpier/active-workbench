from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import time


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    reset_after_seconds: int


class SlidingWindowRateLimiter:
    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._lock = Lock()
        self._buckets: dict[str, deque[float]] = {}

    def take(self, key: str) -> RateLimitDecision:
        now = time()
        cutoff = now - self._window_seconds

        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self._max_requests:
                retry_after_seconds = max(
                    1,
                    math.ceil((bucket[0] + self._window_seconds) - now),
                )
                return RateLimitDecision(
                    allowed=False,
                    limit=self._max_requests,
                    remaining=0,
                    retry_after_seconds=retry_after_seconds,
                    reset_after_seconds=retry_after_seconds,
                )

            bucket.append(now)
            remaining = max(self._max_requests - len(bucket), 0)
            reset_after_seconds = max(
                1,
                math.ceil((bucket[0] + self._window_seconds) - now),
            )
            return RateLimitDecision(
                allowed=True,
                limit=self._max_requests,
                remaining=remaining,
                retry_after_seconds=0,
                reset_after_seconds=reset_after_seconds,
            )
