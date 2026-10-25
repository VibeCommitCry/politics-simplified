"""Every way a run can fail ends in a valid error response: it round-trips through JSON
as a SimplifyResponse with `error` filled, `critic_passed` false and the request's case_id."""

from simplifier.api.schemas import SimplifyResponse
from simplifier.core import pipeline
from tests.fakes import FakeClient, FakeStatusError, entry


def assert_valid_error_response(response, request_):
    parsed = SimplifyResponse.model_validate_json(response.model_dump_json())
    assert parsed.error
    assert parsed.critic_passed is False
    assert parsed.case_id == request_.case_id
    return parsed


def test_every_model_unavailable(request_):
    response = pipeline.run(request_, [entry("first-model")], lambda e: FakeClient([FakeStatusError(503)]))

    parsed = assert_valid_error_response(response, request_)
    assert "no model available" in parsed.error


def test_run_failed_on_a_timeout(request_):
    first = entry("first-model")
    response = pipeline.run(request_, [first], lambda e: FakeClient([TimeoutError("read timed out")]))

    parsed = assert_valid_error_response(response, request_)
    assert "TimeoutError" in parsed.error
    assert parsed.model == first.model
    assert parsed.prompts.writer != ""  # the prompt built before the failure is kept


def test_run_failed_when_the_client_cannot_be_made(request_):
    def missing_key(entry_):
        raise RuntimeError("GEMINI_API_KEY is not set")

    response = pipeline.run(request_, [entry("first-model")], missing_key)

    parsed = assert_valid_error_response(response, request_)
    assert "GEMINI_API_KEY" in parsed.error


def test_unexpected_exception_is_caught(request_, monkeypatch):
    def broken(*args):
        raise ValueError("something unexpected")

    monkeypatch.setattr(pipeline, "_first_available_model", broken)

    response = pipeline.run(request_, [entry("first-model")], lambda e: FakeClient())

    parsed = assert_valid_error_response(response, request_)
    assert "ValueError: something unexpected" in parsed.error
