"""The prompt templates in prompts/<version>/ and the values the builders pass to them."""

from string import Template

import pytest

from simplifier.prompt import builder
from test_prompts_golden import PREVIOUS, PROBLEMS, REQUEST_EMPTY_AGAINST

VERSION_DIR = builder.PROMPTS_DIR / builder.PROMPT_VERSION
STATIC = {"writer", "critic"}


def _rendered_kwargs(monkeypatch) -> dict[str, set[str]]:
    """Runs both builders, recording which keys each template was rendered with."""
    seen: dict[str, set[str]] = {}
    real_render = builder.render

    def recording_render(version, name, **values):
        seen[name] = set(values)
        return real_render(version, name, **values)

    monkeypatch.setattr(builder, "render", recording_render)
    builder.build_writer_prompt(REQUEST_EMPTY_AGAINST, previous=PREVIOUS, problems=PROBLEMS)
    builder.build_critic_prompt(REQUEST_EMPTY_AGAINST, PREVIOUS)
    return seen


def test_placeholders_match_the_values_the_builders_pass(monkeypatch):
    seen = _rendered_kwargs(monkeypatch)
    templates = {path.stem for path in VERSION_DIR.glob("*.md")} - STATIC

    assert set(seen) == templates
    for name, keys in seen.items():
        identifiers = set(Template(builder._read(builder.PROMPT_VERSION, name)).get_identifiers())
        assert identifiers == keys, name


@pytest.mark.parametrize("name", sorted(STATIC))
def test_static_files_have_no_placeholders(name):
    assert Template(builder.static(builder.PROMPT_VERSION, name)).get_identifiers() == []


def test_missing_placeholder_raises():
    with pytest.raises(KeyError):
        builder.render(builder.PROMPT_VERSION, "feedback", answer_begin="", answer_end="", previous="")


def test_dollar_and_braces_in_values_come_through_unchanged():
    text = "kost $x, ${y} en {z} en $$"
    request = REQUEST_EMPTY_AGAINST.model_copy(update={"text": text})

    assert f"\n{text}\n" in builder.build_writer_prompt(request)


def test_every_template_is_valid():
    for path in VERSION_DIR.glob("*.md"):
        assert Template(path.read_text(encoding="utf-8")).is_valid(), path.name
