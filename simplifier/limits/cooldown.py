"""Per-model cooldown, in memory: a model that answers 429 or 503 is left alone for a while."""

import sys
import threading
import time

from ..ai.registry import ModelEntry

COOLDOWN_STATUSES = (429, 503)
COOLDOWN_SECONDS = 60

_state_lock = threading.Lock()
# model name -> (monotonic time the cooldown ends, status code that caused it)
_cooldowns: dict[str, tuple[float, int]] = {}


def start_cooldown(entry: ModelEntry, status: int) -> None:
    with _state_lock:
        _cooldowns[entry.name] = (time.monotonic() + COOLDOWN_SECONDS, status)


def cooldown_status(entry: ModelEntry) -> int | None:
    """The status code that put this model in cooldown, or None when it can be used."""
    with _state_lock:
        cooldown = _cooldowns.get(entry.name)
        if cooldown is None:
            return None
        until, status = cooldown
        if time.monotonic() >= until:
            del _cooldowns[entry.name]
            return None
        return status


def log_skip(entry: ModelEntry, status: int, reason: str) -> None:
    """Skips go to stderr; stdout is reserved for the response."""
    print(f"skip model {entry.name}: status {status} ({reason})", file=sys.stderr)


def reset() -> None:
    with _state_lock:
        _cooldowns.clear()
