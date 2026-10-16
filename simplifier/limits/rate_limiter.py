"""Per-model sliding-window rate limit, in memory: calls wait rather than exceed `rpm`."""

import threading
import time
from collections import deque

from ..ai.registry import ModelEntry

RATE_WINDOW_SECONDS = 60


class RateLimiter:
    """Allows at most `rpm` calls in any 60-second window; `wait` sleeps until there is room."""

    def __init__(self, rpm: int):
        self.rpm = rpm
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            while True:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= RATE_WINDOW_SECONDS:
                    self._calls.popleft()
                if len(self._calls) < self.rpm:
                    break
                time.sleep(RATE_WINDOW_SECONDS - (now - self._calls[0]))
            self._calls.append(now)


_state_lock = threading.Lock()
_limiters: dict[str, RateLimiter] = {}


def wait_for_rate_limit(entry: ModelEntry) -> None:
    """Call right before each request to this model. Returns at once when it has no `rpm`."""
    if entry.rpm is None:
        return
    with _state_lock:
        limiter = _limiters.get(entry.name)
        if limiter is None or limiter.rpm != entry.rpm:
            limiter = _limiters[entry.name] = RateLimiter(entry.rpm)
    limiter.wait()


def reset() -> None:
    with _state_lock:
        _limiters.clear()
