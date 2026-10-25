"""The contract rules that are enforced in code: one test per rule, each changing one field
of a valid base."""

import copy
import json

import pytest
from pydantic import ValidationError

from simplifier.api.schemas import (
    HOOK_MAX_CHARS,
    CriticOutput,
    SimplifyRequest,
    SimplifyResponse,
    WriterOutput,
)
from simplifier.prompt.builder import PROMPT_VERSION
from tests.fakes import GOOD_ANSWER, PASS_VERDICT, SAMPLE

ALLOWED = ["Wonen", "Zorg", "Onderwijs", "Klimaat"]


@pytest.fixture
def answer():
    return copy.deepcopy(GOOD_ANSWER)


@pytest.fixture
def request_data():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def validate_answer(data, allowed=ALLOWED):
    return WriterOutput.model_validate(data, context={"allowed_topics": allowed})


def test_good_answer_is_valid(answer):
    validate_answer(answer)


# --- WriterOutput: hook --------------------------------------------------------


def test_hook_of_exactly_200_characters_is_valid(answer):
    answer["hook"] = "x" * HOOK_MAX_CHARS
    validate_answer(answer)


def test_hook_over_200_characters_is_rejected(answer):
    answer["hook"] = "x" * (HOOK_MAX_CHARS + 1)
    with pytest.raises(ValidationError):
        validate_answer(answer)


def test_empty_hook_is_rejected(answer):
    answer["hook"] = ""
    with pytest.raises(ValidationError):
        validate_answer(answer)


def test_missing_hook_is_rejected(answer):
    del answer["hook"]
    with pytest.raises(ValidationError):
        validate_answer(answer)


# --- WriterOutput: topics ------------------------------------------------------


def test_topic_from_the_allowed_list_is_valid(answer):
    answer["topics"] = ["Zorg"]
    validate_answer(answer)


def test_unknown_topic_is_rejected(answer):
    answer["topics"] = ["Wonen", "Ruimtevaart"]
    with pytest.raises(ValidationError):
        validate_answer(answer)


def test_three_topics_are_valid(answer):
    answer["topics"] = ["Wonen", "Zorg", "Onderwijs"]
    validate_answer(answer)


def test_more_than_three_topics_are_rejected(answer):
    answer["topics"] = ["Wonen", "Zorg", "Onderwijs", "Klimaat"]
    with pytest.raises(ValidationError):
        validate_answer(answer)


def test_no_topics_are_rejected(answer):
    answer["topics"] = []
    with pytest.raises(ValidationError):
        validate_answer(answer)


def test_missing_allowed_topics_context_is_rejected(answer):
    with pytest.raises(ValidationError):
        WriterOutput.model_validate(answer)


# --- WriterOutput: relevance ---------------------------------------------------


@pytest.mark.parametrize("relevance", [1, 5])
def test_relevance_at_the_edges_is_valid(answer, relevance):
    answer["relevance"] = relevance
    validate_answer(answer)


@pytest.mark.parametrize("relevance", [0, 6])
def test_relevance_outside_1_to_5_is_rejected(answer, relevance):
    answer["relevance"] = relevance
    with pytest.raises(ValidationError):
        validate_answer(answer)


def test_missing_relevance_is_rejected(answer):
    del answer["relevance"]
    with pytest.raises(ValidationError):
        validate_answer(answer)


# --- WriterOutput: detail ------------------------------------------------------

SECTIONS = ["waar_gaat_het_over", "wat_betekent_het_voor_jou", "wat_is_er_besloten"]


@pytest.mark.parametrize("section", SECTIONS)
def test_empty_detail_section_is_rejected(answer, section):
    answer["detail"][section] = ""
    with pytest.raises(ValidationError):
        validate_answer(answer)


@pytest.mark.parametrize("section", SECTIONS + ["moeilijke_woorden"])
def test_missing_detail_section_is_rejected(answer, section):
    del answer["detail"][section]
    with pytest.raises(ValidationError):
        validate_answer(answer)


def test_extra_detail_section_is_rejected(answer):
    answer["detail"]["samenvatting"] = "extra"
    with pytest.raises(ValidationError):
        validate_answer(answer)


def test_difficult_word_with_both_fields_is_valid(answer):
    answer["detail"]["moeilijke_woorden"] = [{"woord": "motie", "betekenis": "een verzoek"}]
    validate_answer(answer)


@pytest.mark.parametrize("field", ["woord", "betekenis"])
def test_difficult_word_with_an_empty_field_is_rejected(answer, field):
    word = {"woord": "motie", "betekenis": "een verzoek"}
    word[field] = ""
    answer["detail"]["moeilijke_woorden"] = [word]
    with pytest.raises(ValidationError):
        validate_answer(answer)


def test_difficult_word_with_an_extra_field_is_rejected(answer):
    answer["detail"]["moeilijke_woorden"] = [{"woord": "motie", "betekenis": "verzoek", "bron": "x"}]
    with pytest.raises(ValidationError):
        validate_answer(answer)


def test_extra_top_level_key_is_rejected(answer):
    answer["samenvatting"] = "extra"
    with pytest.raises(ValidationError):
        validate_answer(answer)


# --- WriterOutput: whitespace-only text ------------------------------------------


def test_whitespace_only_hook_is_rejected(answer):
    answer["hook"] = "   "
    with pytest.raises(ValidationError):
        validate_answer(answer)


@pytest.mark.parametrize("section", SECTIONS)
def test_whitespace_only_detail_section_is_rejected(answer, section):
    answer["detail"][section] = " \n "
    with pytest.raises(ValidationError):
        validate_answer(answer)


@pytest.mark.parametrize("field", ["woord", "betekenis"])
def test_whitespace_only_difficult_word_field_is_rejected(answer, field):
    word = {"woord": "motie", "betekenis": "een verzoek"}
    word[field] = "  "
    answer["detail"]["moeilijke_woorden"] = [word]
    with pytest.raises(ValidationError):
        validate_answer(answer)


# --- CriticOutput ----------------------------------------------------------------


def test_passing_verdict_is_valid():
    CriticOutput.model_validate(PASS_VERDICT)


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_outside_0_to_1_is_rejected(confidence):
    with pytest.raises(ValidationError):
        CriticOutput.model_validate({**PASS_VERDICT, "confidence": confidence})


def test_missing_passed_is_rejected():
    verdict = dict(PASS_VERDICT)
    del verdict["passed"]
    with pytest.raises(ValidationError):
        CriticOutput.model_validate(verdict)


def test_passed_with_problems_is_rejected():
    with pytest.raises(ValidationError):
        CriticOutput.model_validate({**PASS_VERDICT, "problems": ["x"]})


def test_extra_verdict_key_is_rejected():
    with pytest.raises(ValidationError):
        CriticOutput.model_validate({**PASS_VERDICT, "reden": "x"})


# --- SimplifyRequest ---------------------------------------------------------------


def test_sample_request_is_valid(request_data):
    SimplifyRequest.model_validate(request_data)


def test_empty_text_is_rejected(request_data):
    request_data["text"] = ""
    with pytest.raises(ValidationError):
        SimplifyRequest.model_validate(request_data)


def test_no_submitters_are_rejected(request_data):
    request_data["submitters"] = []
    with pytest.raises(ValidationError):
        SimplifyRequest.model_validate(request_data)


def test_no_topics_in_the_request_are_rejected(request_data):
    request_data["topics"] = []
    with pytest.raises(ValidationError):
        SimplifyRequest.model_validate(request_data)


def test_negative_seats_are_rejected(request_data):
    request_data["vote"]["for"] = [{"party": "VVD", "seats": -1}]
    with pytest.raises(ValidationError):
        SimplifyRequest.model_validate(request_data)


def test_unknown_outcome_is_rejected(request_data):
    request_data["vote"]["outcome"] = "aangehouden"
    with pytest.raises(ValidationError):
        SimplifyRequest.model_validate(request_data)


def test_invalid_vote_date_is_rejected(request_data):
    request_data["vote"]["date"] = "gisteren"
    with pytest.raises(ValidationError):
        SimplifyRequest.model_validate(request_data)


@pytest.mark.parametrize("field", ["case_id", "title", "text", "submitters", "vote", "topics"])
def test_missing_request_field_is_rejected(request_data, field):
    del request_data[field]
    with pytest.raises(ValidationError):
        SimplifyRequest.model_validate(request_data)


def test_related_is_optional(request_data):
    request_data.pop("related", None)
    assert SimplifyRequest.model_validate(request_data).related == []


# --- SimplifyResponse --------------------------------------------------------------


def full_response(**changes):
    data = {
        "case_id": "2026Z00001",
        **GOOD_ANSWER,
        "critic_passed": True,
        "prompt_version": PROMPT_VERSION,
    }
    return {**data, **changes}


def test_full_response_is_valid():
    SimplifyResponse.model_validate(full_response())


@pytest.mark.parametrize(
    "change", [{"hook": ""}, {"detail": None}, {"topics": []}, {"relevance": None}]
)
def test_response_without_error_needs_all_content(change):
    with pytest.raises(ValidationError):
        SimplifyResponse.model_validate(full_response(**change))


def test_error_response_with_empty_content_is_valid():
    SimplifyResponse(case_id="2026Z00001", prompt_version=PROMPT_VERSION, error="boom")


def test_error_response_cannot_have_passed():
    with pytest.raises(ValidationError):
        SimplifyResponse(case_id="2026Z00001", prompt_version=PROMPT_VERSION, error="boom", critic_passed=True)
