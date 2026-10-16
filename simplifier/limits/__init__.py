"""In-memory, per-model limits so no provider is called too often."""

from . import cooldown, rate_limiter


def reset_state() -> None:
    """Forgets all rate-limit history and cooldowns (for tests)."""
    rate_limiter.reset()
    cooldown.reset()
