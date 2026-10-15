"""Per-host rate limiter: enforces a minimum interval between consecutive requests."""

import threading
import time


class RateLimiter:
    def __init__(self, min_interval):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self):
        """Block until it is our turn; return the seconds waited (recorded as timings.wait_s)."""
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_at - now)
            if delay:
                time.sleep(delay)
            self._next_at = time.monotonic() + self.min_interval
            return delay
