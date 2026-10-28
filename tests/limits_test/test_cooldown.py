"""The 60 s cooldown of a model that answered 429 or 503."""

from simplifier.core import pipeline
from simplifier.limits import cooldown, rate_limiter
from tests.fakes import FakeClient, FakeStatusError, entry


def test_cooldown_ends_after_60_seconds(request_, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rate_limiter.time, "monotonic", lambda: now[0])
    first = entry("first-model")
    client = FakeClient([FakeStatusError(503)])
    pipeline.run(request_, [first], lambda e: client)

    now[0] += cooldown.COOLDOWN_SECONDS
    response = pipeline.run(request_, [first], lambda e: client)

    assert response.error is None
    assert client.calls == 2
