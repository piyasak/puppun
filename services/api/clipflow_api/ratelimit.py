"""Small in-process sliding-window limiter for credential endpoints (PRD §14: token guessing).

Per API process only. A multi-instance deployment needs a shared store (Redis) — tracked in
the backlog; the 256-bit token secret is the real defence, this only slows noisy clients.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from .errors import ApiError


class SlidingWindow:
    def __init__(self, limit: int, window_s: float):
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                retry = max(1, int(self.window_s - (now - q[0])) + 1)
                raise ApiError(429, "RATE_LIMITED", "ส่งคำขอบ่อยเกินไป กรุณารอสักครู่", {"retry_after_s": retry})
            q.append(now)
