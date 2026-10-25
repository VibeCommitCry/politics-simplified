"""Fallback, retry and the writer ⇄ critic loop, with fake clients. Needs no API key."""

import json

from simplifier.core import pipeline
from simplifier.limits import cooldown
from tests.fakes import (
    CRITIC_PROMPT_MARK,
    GOOD_ANSWER,
    FakeClient,
    FakeStatusError,
    entry,
    fail_verdict,
)


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


# --- Writer ⇄ critic loop -----------------------------------------------------


def test_critic_passes_in_round_one(request_, capsys):
    first = entry("first-model")
    client = FakeClient()

    response = pipeline.run(request_, [first], lambda e: client)

    assert response.error is None
    assert response.critic_passed is True
    assert response.rounds == 1
    assert response.confidence == 0.9
    assert response.critic_problems == []
    assert CRITIC_PROMPT_MARK in response.prompts.critic
    assert client.critic_arguments["temperature"] == 0.0
    assert "round model=first-model-model round=1 passed=true confidence=0.90" in capsys.readouterr().err


def test_critic_problems_go_to_the_writer_in_the_next_round(request_):
    first = entry("first-model")
    client = FakeClient(verdicts=[fail_verdict("De datum klopt niet.")])

    response = pipeline.run(request_, [first], lambda e: client)

    assert response.critic_passed is True
    assert response.rounds == 2
    assert client.calls == 2
    assert "De datum klopt niet." not in client.writer_prompts[0]
    assert "De datum klopt niet." in client.writer_prompts[1]
    assert GOOD_ANSWER["hook"] in client.writer_prompts[1]  # the previous answer is shown
    assert response.prompts.writer == client.writer_prompts[1]  # only the last round is kept


def test_not_passed_after_three_rounds_is_returned_for_review(request_):
    first = entry("first-model")
    client = FakeClient(verdicts=[fail_verdict("a"), fail_verdict("b"), fail_verdict("c")])

    response = pipeline.run(request_, [first], lambda e: client)

    assert response.error is None
    assert response.critic_passed is False
    assert response.rounds == 3
    assert response.confidence == 0.4
    assert response.critic_problems == ["c"]
    assert response.hook == GOOD_ANSWER["hook"]
    assert client.critic_calls == 3


def test_critic_503_restarts_the_run_on_the_next_model(request_):
    first, second = entry("first-model"), entry("second-model")
    clients = {
        "first-model": FakeClient(verdicts=[fail_verdict("a"), FakeStatusError(503)]),
        "second-model": FakeClient(),
    }

    response = pipeline.run(request_, [first, second], lambda e: clients[e.name])

    assert response.model == second.model
    assert response.rounds == 1  # started over, not continued at round 2
    assert clients["second-model"].calls == 1
    assert cooldown.cooldown_status(first) == 503


def test_prompts_are_not_shared_between_runs(request_):
    first = entry("first-model")
    failing = pipeline.run(request_, [first], lambda e: FakeClient([FakeStatusError(400)]))
    response = pipeline.run(request_, [first], lambda e: FakeClient())

    assert failing.prompts.critic == ""  # the critic was never reached
    assert response.prompts.critic != ""
    assert failing.prompts is not response.prompts


def test_fatal_error_in_round_two_keeps_the_prompts(request_):
    first = entry("first-model")
    client = FakeClient(
        failures=[json.dumps(GOOD_ANSWER), FakeStatusError(400)],
        verdicts=[fail_verdict("De datum klopt niet.")],
    )

    response = pipeline.run(request_, [first], lambda e: client)

    assert "400" in response.error
    assert response.model == first.model
    assert "De datum klopt niet." in response.prompts.writer  # the round 2 writer prompt
    assert CRITIC_PROMPT_MARK in response.prompts.critic  # from round 1


def test_inconsistent_verdict_is_retried(request_):
    first = entry("first-model")
    client = FakeClient(verdicts=[json.dumps({"passed": True, "confidence": 0.9, "problems": ["x"]})])

    response = pipeline.run(request_, [first], lambda e: client)

    assert response.critic_passed is True
    assert client.critic_calls == 2
    assert client.calls == 1  # only the critic call was retried


def test_two_bad_verdicts_fall_back_to_the_next_model(request_):
    first, second = entry("first-model"), entry("second-model")
    clients = {"first-model": FakeClient(verdicts=["nope", "nope"]), "second-model": FakeClient()}

    response = pipeline.run(request_, [first, second], lambda e: clients[e.name])

    assert response.model == second.model
    assert cooldown.cooldown_status(first) is None
