"""Loads models.yaml, builds OpenAI-compatible clients, and tracks rate limits and cooldowns."""

import os
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_FILE = REPO_ROOT / "models.yaml"

# Symfony waits 120 s for the whole request, so a single call must stay well below that.
REQUEST_TIMEOUT_SECONDS = 60

# A model that answers with one of these is busy or over its limit: leave it alone for a while.
COOLDOWN_STATUSES = (429, 503)
COOLDOWN_SECONDS = 60

RATE_WINDOW_SECONDS = 60

BAD_TEXT_LOG_CHARS = 300


class ModelEntry(BaseModel):
    name: str
    base_url: str
    model: str
    api_key_env: str
    # Requests per minute allowed by the provider; no limit is applied when left out.
    rpm: int | None = Field(default=None, ge=1)
    # Extra keyword arguments for chat.completions.create, e.g. max_tokens or reasoning_effort.
    options: dict[str, Any] = Field(default_factory=dict)

    @property
    def provider(self) -> str:
        """The part of `name` before the first dash, e.g. "mistral-small" -> "mistral"."""
        return self.name.split("-", 1)[0]


def load_models(path: Path = MODELS_FILE) -> list[ModelEntry]:
    """Returns the models in the order they should be tried."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = [ModelEntry.model_validate(entry) for entry in data.get("models") or []]
    if not models:
        raise ValueError(f"no models found in {path}")
    return models


def client_for(entry: ModelEntry) -> OpenAI:
    """Returns an `openai` client for this entry; the key comes from the environment or `.env`."""
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get(entry.api_key_env)
    if not api_key:
        raise RuntimeError(f"{entry.api_key_env} is not set (see .env.example)")
    # No retries inside the client: a failing model is handled by moving to the next one.
    return OpenAI(
        base_url=entry.base_url,
        api_key=api_key,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )


# --- Rate limit and cooldown (in memory, per model name) ----------------------


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
# model name -> (monotonic time the cooldown ends, status code that caused it)
_cooldowns: dict[str, tuple[float, int]] = {}


def wait_for_rate_limit(entry: ModelEntry) -> None:
    """Call right before each request to this model. Returns at once when it has no `rpm`."""
    if entry.rpm is None:
        return
    with _state_lock:
        limiter = _limiters.get(entry.name)
        if limiter is None or limiter.rpm != entry.rpm:
            limiter = _limiters[entry.name] = RateLimiter(entry.rpm)
    limiter.wait()


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


def log_bad_generation(entry: ModelEntry, code: str, text: str) -> None:
    """Logs a rejected answer with the start of whatever text the model returned."""
    print(
        f"bad generation from model {entry.name}: {code}, returned text: {text[:BAD_TEXT_LOG_CHARS]!r}",
        file=sys.stderr,
    )


def reset_state() -> None:
    """Forgets all rate-limit history and cooldowns (for tests)."""
    with _state_lock:
        _limiters.clear()
        _cooldowns.clear()
