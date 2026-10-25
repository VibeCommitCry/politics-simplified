from openai import OpenAI
from pydantic import ValidationError

from ..ai.registry import ModelEntry
from ..api.schemas import SimplifyRequest, WriterOutput
from .generation import VALIDATION_FAILED, BadGeneration, prompt_to_json

WRITER_TEMPERATURE = 0.3


def write(
    request: SimplifyRequest, entry: ModelEntry, client: OpenAI, writer_prompt: str
) -> WriterOutput:
    """One writer attempt. Raises BadGeneration for an unusable answer."""
    content = prompt_to_json(entry, client, writer_prompt, WRITER_TEMPERATURE)
    try:
        return WriterOutput.model_validate_json(content, context={"allowed_topics": request.topics})
    except ValidationError as exc:
        raise BadGeneration(VALIDATION_FAILED, content, str(exc)) from exc
