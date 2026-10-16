"""Runs one motie through the writer, moving to the next model when one is busy or writes
something unusable. The critic loop comes later."""

import sys

from openai import OpenAI
from pydantic import ValidationError

from ..ai.client import client_for
from ..ai.registry import ModelEntry, load_models
from ..api.schemas import Prompts, SimplifyRequest, SimplifyResponse, WriterOutput
from ..limits.cooldown import COOLDOWN_SECONDS, COOLDOWN_STATUSES, cooldown_status, log_skip, start_cooldown
from ..limits.rate_limiter import wait_for_rate_limit
from ..prompt.builder import PROMPT_VERSION, build_writer_prompt

# A model gets this many tries to produce a usable answer before the next model takes over.
BAD_GENERATION_ATTEMPTS = 2

BAD_TEXT_LOG_CHARS = 300

JSON_VALIDATE_FAILED = "json_validate_failed"
VALIDATION_FAILED = "validation_failed"


def run(
    request: SimplifyRequest,
    models: list[ModelEntry] | None = None,
    client_factory=client_for,
) -> SimplifyResponse:
    """Writes the hook and detail text for one motie. Never raises: failures end up in `error`.

    Models are tried in order. One that answers 429 or 503 goes into cooldown and the run
    restarts with the next one; models in cooldown are skipped. One that writes an unusable
    answer gets one more try and then the next model takes over, without a cooldown.
    Any other failure ends the run.

    `models` and `client_factory` can be passed in to run without models.yaml or an API key (tests).
    """
    entry = None
    writer_prompt = ""
    try:
        writer_prompt = build_writer_prompt(request)
        skipped = []
        for entry in models if models is not None else load_models():
            status = cooldown_status(entry)
            if status is not None:
                log_skip(entry, status, "cooling down")
                skipped.append(f"{entry.name} ({status})")
                continue
            client = client_factory(entry)
            failure = ""
            for _ in range(BAD_GENERATION_ATTEMPTS):
                try:
                    return _write(request, entry, client, writer_prompt)
                except BadGeneration as bad:
                    log_bad_generation(entry, bad.code, bad.text)
                    failure = bad.code
                except Exception as exc:
                    status = getattr(exc, "status_code", None)
                    if status not in COOLDOWN_STATUSES:
                        raise
                    start_cooldown(entry, status)
                    log_skip(entry, status, f"cooling down for {COOLDOWN_SECONDS} s, trying the next model")
                    failure = str(status)
                    break
            skipped.append(f"{entry.name} ({failure})")
        raise RuntimeError(f"no model available: {', '.join(skipped)}")
    except Exception as exc:
        return error_response(
            request.case_id, f"{type(exc).__name__}: {exc}", entry=entry, writer_prompt=writer_prompt
        )


def error_response(
    case_id: str,
    error: str,
    entry: ModelEntry | None = None,
    writer_prompt: str = "",
) -> SimplifyResponse:
    """A valid response for a failed run: `error` filled, `critic_passed` false."""
    return SimplifyResponse(
        case_id=case_id,
        critic_passed=False,
        model=entry.model if entry else "",
        provider=entry.provider if entry else "",
        prompt_version=PROMPT_VERSION,
        prompts=Prompts(writer=writer_prompt),
        error=error,
    )


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


def _failed_generation(exc: Exception) -> str:
    """The text the provider rejected, when it sends that along with the error."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return ""
    nested = body.get("error")
    text = body.get("failed_generation") or (nested.get("failed_generation") if isinstance(nested, dict) else "")
    return text or ""


def _write(
    request: SimplifyRequest, entry: ModelEntry, client: OpenAI, writer_prompt: str
) -> SimplifyResponse:
    """One writer attempt with one model. Raises BadGeneration for an unusable answer."""
    wait_for_rate_limit(entry)
    arguments = {
        "model": entry.model,
        "messages": [{"role": "user", "content": writer_prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        **entry.options,
    }
    try:
        completion = client.chat.completions.create(**arguments)
    except Exception as exc:
        # Some providers check the JSON themselves and answer 400 instead of returning the text.
        if getattr(exc, "status_code", None) == 400 and getattr(exc, "code", None) == JSON_VALIDATE_FAILED:
            raise BadGeneration(JSON_VALIDATE_FAILED, _failed_generation(exc), str(exc)) from exc
        raise
    content = completion.choices[0].message.content or ""
    try:
        # Also rejects text that is not JSON at all.
        output = WriterOutput.model_validate_json(content, context={"allowed_topics": request.topics})
    except ValidationError as exc:
        raise BadGeneration(VALIDATION_FAILED, content, str(exc)) from exc
    return SimplifyResponse(
        case_id=request.case_id,
        hook=output.hook,
        detail=output.detail,
        topics=output.topics,
        relevance=output.relevance,
        # No critic yet, so nothing has been approved.
        critic_passed=False,
        confidence=0.0,
        rounds=1,
        model=entry.model,
        provider=entry.provider,
        prompt_version=PROMPT_VERSION,
        prompts=Prompts(writer=writer_prompt),
    )
