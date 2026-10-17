"""One JSON call to a model, shared by the writer and the critic."""

import sys

from openai import OpenAI

from ..ai.registry import ModelEntry
from ..limits.rate_limiter import wait_for_rate_limit

BAD_TEXT_LOG_CHARS = 300

JSON_VALIDATE_FAILED = "json_validate_failed"
VALIDATION_FAILED = "validation_failed"


class BadGeneration(Exception):
    """The model answered, but not with something usable."""

    def __init__(self, code: str, text: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.text = text


def log_bad_generation(entry: ModelEntry, code: str, text: str) -> None:
    """Logs a rejected answer with the start of whatever text the model returned."""
    print(
        f"bad generation from model {entry.name}: {code}, returned text: {text[:BAD_TEXT_LOG_CHARS]!r}",
        file=sys.stderr,
    )


def complete_json(entry: ModelEntry, client: OpenAI, prompt: str, temperature: float) -> str:
    """Sends the prompt as one user message in JSON mode and returns the answer text.

    Waits for the model's rate limit first. Raises BadGeneration when the provider
    rejects the JSON itself; other API errors are raised as they are.
    """
    wait_for_rate_limit(entry)
    arguments = {
        "model": entry.model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        **entry.options,
    }
    try:
        completion = client.chat.completions.create(**arguments)
    except Exception as exc:
        # Some providers check the JSON themselves and answer 400 instead of returning the text.
        if getattr(exc, "status_code", None) == 400 and getattr(exc, "code", None) == JSON_VALIDATE_FAILED:
            raise BadGeneration(JSON_VALIDATE_FAILED, _failed_generation(exc), str(exc)) from exc
        raise
    return completion.choices[0].message.content or ""


def _failed_generation(exc: Exception) -> str:
    """The text the provider rejected, when it sends that along with the error."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return ""
    nested = body.get("error")
    text = body.get("failed_generation") or (nested.get("failed_generation") if isinstance(nested, dict) else "")
    return text or ""
