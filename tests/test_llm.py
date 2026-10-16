"""Fallback, cooldown and rate limit, with fake clients. Needs no API key."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplifier import limits
from simplifier.core import pipeline
from simplifier.limits import cooldown, rate_limiter
from simplifier.ai.registry import ModelEntry
from simplifier.limits.rate_limiter import RateLimiter
from simplifier.api.schemas import SimplifyRequest

SAMPLE = Path(__file__).parent / "samples" / "example.json"

GOOD_ANSWER = {
    "hook": "Moet je huur een jaar gelijk blijven?",
    "detail": {
        "waar_gaat_het_over": "a",
        "wat_betekent_het_voor_jou": "b",
        "wat_is_er_besloten": "c",
        "moeilijke_woorden": [],
    },
    "topics": ["Wonen"],
    "relevance": 4,
}


class FakeStatusError(Exception):
    """Looks like openai.APIStatusError: the pipeline only reads `status_code`."""

    def __init__(self, status_code: int, code: str | None = None, body: dict | None = None):
        super().__init__(f"Error code: {status_code}")
        self.status_code = status_code
        self.code = code
        self.body = body


class FakeClient:
    """Works through `failures` first (one per call), then returns a good answer.

    A failure is an exception to raise, or a string to return as the model's text.
    """

    def __init__(self, failures=()):
        self.failures = list(failures)
        self.calls = 0
        self.last_arguments = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        self.last_arguments = kwargs
        content = json.dumps(GOOD_ANSWER)
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            content = failure
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def entry(name: str, **extra) -> ModelEntry:
    return ModelEntry(
        name=name, base_url="http://fake", model=f"{name}-model", api_key_env="NONE", **extra
    )


@pytest.fixture(autouse=True)
def clean_state():
    limits.reset_state()
    yield
    limits.reset_state()


@pytest.fixture
def request_():
    return SimplifyRequest.model_validate(json.loads(SAMPLE.read_text(encoding="utf-8")))


def test_503_moves_to_next_model_without_retrying(request_, capsys):
    first, second = entry("first-model"), entry("second-model")
    # Would succeed on a second call, so a retry of the same model would show up as calls == 2.
    clients = {"first-model": FakeClient([FakeStatusError(503)]), "second-model": FakeClient()}

    response = pipeline.run(request_, [first, second], lambda e: clients[e.name])

    assert response.error is None
    assert response.model == second.model
    assert clients["first-model"].calls == 1
    assert clients["second-model"].calls == 1
    err = capsys.readouterr().err
    assert "first-model" in err and "503" in err


def test_model_in_cooldown_is_skipped_on_the_next_run(request_, capsys):
    first, second = entry("first-model"), entry("second-model")
    clients = {"first-model": FakeClient([FakeStatusError(429)]), "second-model": FakeClient()}
    pipeline.run(request_, [first, second], lambda e: clients[e.name])
    capsys.readouterr()

    response = pipeline.run(request_, [first, second], lambda e: clients[e.name])

    assert response.model == second.model
    assert clients["first-model"].calls == 1  # not called again while cooling down
    err = capsys.readouterr().err
    assert "first-model" in err and "429" in err


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


def test_all_models_unavailable_gives_error_response(request_):
    first = entry("first-model")
    response = pipeline.run(request_, [first], lambda e: FakeClient([FakeStatusError(503)]))

    assert "no model available" in response.error
    assert response.critic_passed is False
    json.loads(response.model_dump_json())


def test_other_errors_do_not_cool_down(request_):
    first, second = entry("first-model"), entry("second-model")
    clients = {"first-model": FakeClient([FakeStatusError(400)]), "second-model": FakeClient()}

    response = pipeline.run(request_, [first, second], lambda e: clients[e.name])

    assert "400" in response.error
    assert clients["second-model"].calls == 0
    assert cooldown.cooldown_status(first) is None


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


def test_invalid_json_is_retried_once_on_the_same_model(request_, capsys):
    first, second = entry("first-model"), entry("second-model")
    bad_text = "Hier is het antwoord: " + "x" * 400
    clients = {"first-model": FakeClient([bad_text]), "second-model": FakeClient()}

    response = pipeline.run(request_, [first, second], lambda e: clients[e.name])

    assert response.error is None
    assert response.model == first.model
    assert clients["first-model"].calls == 2
    assert clients["second-model"].calls == 0
    err = capsys.readouterr().err
    assert "first-model" in err and "validation_failed" in err
    assert bad_text[:300] in err and bad_text[:301] not in err


def test_answer_that_breaks_a_rule_is_retried(request_):
    first = entry("first-model")
    client = FakeClient([json.dumps({**GOOD_ANSWER, "hook": "x" * 201})])

    response = pipeline.run(request_, [first], lambda e: client)

    assert response.error is None
    assert client.calls == 2


def test_json_validate_failed_from_the_api_is_retried(request_, capsys):
    first = entry("first-model")
    error = FakeStatusError(400, "json_validate_failed", {"failed_generation": '{"hook": "half'})
    client = FakeClient([error])

    response = pipeline.run(request_, [first], lambda e: client)

    assert response.error is None
    assert client.calls == 2
    err = capsys.readouterr().err
    assert "first-model" in err and "json_validate_failed" in err and '{"hook": "half' in err


def test_two_bad_generations_fall_back_to_the_next_model(request_):
    first, second = entry("first-model"), entry("second-model")
    clients = {"first-model": FakeClient(["not json", "still not json"]), "second-model": FakeClient()}

    response = pipeline.run(request_, [first, second], lambda e: clients[e.name])

    assert response.model == second.model
    assert clients["first-model"].calls == 2
    assert cooldown.cooldown_status(first) is None  # a bad answer is not a busy provider


def test_bad_generations_on_every_model_give_error_response(request_):
    first = entry("first-model")
    response = pipeline.run(request_, [first], lambda e: FakeClient(["not json", "not json"]))

    assert "first-model (validation_failed)" in response.error
    json.loads(response.model_dump_json())


def test_options_are_passed_to_the_request(request_):
    first = entry("first-model", options={"max_tokens": 4000, "reasoning_effort": "low"})
    client = FakeClient()

    pipeline.run(request_, [first], lambda e: client)

    assert client.last_arguments["max_tokens"] == 4000
    assert client.last_arguments["reasoning_effort"] == "low"
    assert client.last_arguments["model"] == first.model
