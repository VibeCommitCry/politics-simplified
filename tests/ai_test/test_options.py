"""A model entry's `options` reach chat.completions.create."""

from simplifier.core import pipeline
from tests.fakes import FakeClient, entry


def test_options_are_passed_to_the_request(request_):
    first = entry("first-model", options={"max_tokens": 4000, "reasoning_effort": "low"})
    client = FakeClient()

    pipeline.run(request_, [first], lambda e: client)

    assert client.last_arguments["max_tokens"] == 4000
    assert client.last_arguments["reasoning_effort"] == "low"
    assert client.last_arguments["model"] == first.model
