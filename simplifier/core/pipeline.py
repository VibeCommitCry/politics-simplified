"""Runs one motie through the writer ⇄ critic loop on one model, moving to the next model
when one is busy or writes something unusable."""

import sys
import time
from collections.abc import Callable
from typing import TypeVar

from openai import OpenAI
from pydantic import ValidationError

from simplifier.core.writer import _write

from ..ai.client import client_for
from ..ai.registry import ModelEntry, load_models
from ..api.schemas import Prompts, SimplifyRequest, SimplifyResponse, WriterOutput
from ..limits.cooldown import (
    COOLDOWN_SECONDS,
    COOLDOWN_STATUSES,
    cooldown_status,
    log_skip,
    start_cooldown,
)
from ..prompt.builder import PROMPT_VERSION, build_critic_prompt, build_writer_prompt
from . import critic
from .generation import (
    VALIDATION_FAILED,
    BadGeneration,
    complete_json,
    log_bad_generation,
)
from .readability import readability

# A model gets this many tries per call to produce a usable answer before the next model takes over.
BAD_GENERATION_ATTEMPTS = 2

MAX_ROUNDS = 3

WRITER_TEMPERATURE = 0.3

T = TypeVar("T")


def run(
    request: SimplifyRequest,
    models: list[ModelEntry] | None = None,
    client_factory=client_for,
) -> SimplifyResponse:
    """Writes and checks the hook and detail text for one motie. Never raises: failures end up in `error`.

    Models are tried in order and one model does the whole run, writer and critic alike.
    One that answers 429 or 503 goes into cooldown and the run restarts from round 1 with
    the next one; models in cooldown are skipped. One that writes an unusable answer gets
    one more try for that call, and then the next model restarts the run, without a cooldown.
    Any other failure ends the run.

    `models` and `client_factory` can be passed in to run without models.yaml or an API key (tests).
    """
    entry = None
    try:
        skipped = []
        # select model through send list or models in models.yaml
        for entry in models if models is not None else load_models():
            status = cooldown_status(entry)
            if status is not None:
                log_skip(entry, status, "cooling down")
                skipped.append(f"{entry.name} ({status})")
                continue

            try:
                return _run_with_model(request, entry, client_factory(entry))
            except BadGeneration as bad:
                failure = bad.code
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status not in COOLDOWN_STATUSES:
                    raise
                start_cooldown(entry, status)
                log_skip(
                    entry,
                    status,
                    f"cooling down for {COOLDOWN_SECONDS} s, trying the next model",
                )
                failure = str(status)
            skipped.append(f"{entry.name} ({failure})")
        raise RuntimeError(f"no model available: {', '.join(skipped)}")
    except Exception as exc:
        return error_response(
            request.case_id,
            f"{type(exc).__name__}: {exc}",
            entry=entry,
        )


def error_response(
    case_id: str,
    error: str,
    entry: ModelEntry | None = None,
    prompts: Prompts | None = None,
) -> SimplifyResponse:
    """A valid response for a failed run: `error` filled, `critic_passed` false."""
    return SimplifyResponse(
        case_id=case_id,
        critic_passed=False,
        model=entry.model if entry else "",
        provider=entry.provider if entry else "",
        prompt_version=PROMPT_VERSION,
        prompts=prompts or Prompts(),
        error=error,
    )


def _run_with_model(
    request: SimplifyRequest,
    entry: ModelEntry,
    client: OpenAI,
    prompts=Prompts(),
) -> SimplifyResponse:
    """Up to MAX_ROUNDS of writer then critic, all on this model. `prompts` keeps the last round's prompts.

    Not passing after the last round is not an error: the answer goes back for manual review.
    """
    output = None
    verdict = None
    for round_ in range(1, MAX_ROUNDS + 1):
        started = time.monotonic()
        prompts.writer = build_writer_prompt(
            request, previous=output, problems=verdict.problems if verdict else None
        )

        output = _with_retry(
            entry, lambda: _write(request, entry, client, prompts.writer)
        )
        
        prompts.critic = build_critic_prompt(request, output)
        
        verdict = _with_retry(
            entry, lambda: critic.review(entry, client, prompts.critic)
        )
        log_round(
            entry,
            round_,
            verdict.passed,
            verdict.confidence,
            time.monotonic() - started,
        )
        if verdict.passed:
            break
    return SimplifyResponse(
        case_id=request.case_id,
        hook=output.hook,
        detail=output.detail,
        topics=output.topics,
        relevance=output.relevance,
        critic_passed=verdict.passed,
        confidence=verdict.confidence,
        rounds=round_,
        critic_problems=verdict.problems,
        readability=readability(request.text, output.detail),
        model=entry.model,
        provider=entry.provider,
        prompt_version=PROMPT_VERSION,
        prompts=prompts.model_copy(),
    )


def _with_retry(entry: ModelEntry, attempt: Callable[[], T]) -> T:
    """Calls `attempt` up to BAD_GENERATION_ATTEMPTS times; re-raises the last BadGeneration."""
    for tries_left in range(BAD_GENERATION_ATTEMPTS - 1, -1, -1):
        try:
            return attempt()
        except BadGeneration as bad:
            log_bad_generation(entry, bad.code, bad.text)
            if not tries_left:
                raise


def log_round(
    entry: ModelEntry, round_: int, passed: bool, confidence: float, duration: float
) -> None:
    print(
        f"round model={entry.model} round={round_} passed={str(passed).lower()} "
        f"confidence={confidence:.2f} duration={duration:.2f}s",
        file=sys.stderr,
    )
