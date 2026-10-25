"""Flesch-Douma scores of the motie and of the simplified detail."""

from simplifier.api.schemas import Detail
from simplifier.core import pipeline, readability
from tests.fakes import GOOD_ANSWER, FakeClient, FakeStatusError, entry


def test_readability_scores_original_and_detail(request_):
    response = pipeline.run(request_, [entry("first-model")], lambda e: FakeClient())

    detail = Detail.model_validate(GOOD_ANSWER["detail"])
    assert response.readability.before == readability.flesch_douma(request_.text)
    assert response.readability.after == readability.flesch_douma(readability.detail_text(detail))


def test_readability_leaves_out_the_word_list():
    detail = Detail(
        waar_gaat_het_over="Een.",
        wat_betekent_het_voor_jou="Twee.",
        wat_is_er_besloten="Drie.",
        moeilijke_woorden=[{"woord": "motie", "betekenis": "verzoek"}],
    )
    assert readability.detail_text(detail) == "Een.\n\nTwee.\n\nDrie."


def test_dutch_score_is_higher_for_simpler_text():
    simple = "De kat zit op de mat. Het is warm."
    hard = "Overwegende dat de regering onvoldoende uitvoeringsmogelijkheden heeft geïnventariseerd."
    assert readability.flesch_douma(simple) > readability.flesch_douma(hard)


def test_error_response_has_no_readability(request_):
    response = pipeline.run(request_, [entry("first-model")], lambda e: FakeClient([FakeStatusError(503)]))

    assert response.error is not None
    assert response.readability is None
