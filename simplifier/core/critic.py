"""The critic: checks one writer answer against the request."""

from openai import OpenAI
from pydantic import ValidationError

from ..ai.registry import ModelEntry
from ..api.schemas import CriticOutput
from .generation import VALIDATION_FAILED, BadGeneration, prompt_to_json

# The critic judges rather than writes, so it gets no room to vary.
CRITIC_TEMPERATURE = 0.0


def _review(entry: ModelEntry, client: OpenAI, critic_prompt: str) -> CriticOutput:
    """One critic attempt. Raises BadGeneration for an unusable verdict."""
    content = prompt_to_json(entry, client, critic_prompt, CRITIC_TEMPERATURE)
    try:
        return CriticOutput.model_validate_json(content)
    except ValidationError as exc:
        raise BadGeneration(VALIDATION_FAILED, content, str(exc)) from exc
