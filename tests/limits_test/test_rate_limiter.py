"""The sliding-window rate limiter."""

from simplifier.limits import rate_limiter
from simplifier.limits.rate_limiter import RateLimiter


def test_rate_limiter_waits_instead_of_exceeding_rpm(monkeypatch):
    now = [0.0]
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(rate_limiter.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(rate_limiter.time, "sleep", fake_sleep)
    limiter = RateLimiter(rpm=2)

    limiter.wait()
    now[0] = 10.0
    limiter.wait()
    assert sleeps == []

    limiter.wait()  # third call within the minute: waits until the first one is 60 s old
    assert sleeps == [50.0]
