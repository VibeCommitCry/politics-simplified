"""Runs one motie through the writer. The critic loop and model fallback come later."""

import json
import re
from pathlib import Path

from .llm import REPO_ROOT, ModelEntry, client_for, load_models
from .models import PartyVote, Prompts, SimplifyRequest, SimplifyResponse, WriterOutput

PROMPT_VERSION = "v1"
PROMPTS_DIR = REPO_ROOT / "prompts"

# The motie text is untrusted data. It is placed between these markers and the
# prompt tells the model never to follow instructions found between them.
TEXT_BEGIN = "<<<MOTIETEKST_BEGIN>>>"
TEXT_END = "<<<MOTIETEKST_EINDE>>>"

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def _untrusted(value: str) -> str:
    """Removes the markers from external text so it cannot close the data block itself."""
    return value.replace(TEXT_BEGIN, "").replace(TEXT_END, "").strip()


def _format_parties(votes: list[PartyVote]) -> str:
    if not votes:
        return "- (geen partijen)"
    return "\n".join(
        f"- {_untrusted(vote.party)}: {vote.seats} {'zetel' if vote.seats == 1 else 'zetels'}"
        for vote in votes
    )


def build_writer_prompt(request: SimplifyRequest, version: str = PROMPT_VERSION) -> str:
    """Fills prompts/<version>/writer.md with the request data."""
    template = (PROMPTS_DIR / version / "writer.md").read_text(encoding="utf-8")
    vote = request.vote
    values = {
        "title": _untrusted(request.title),
        "submitters": "\n".join(
            f"- {_untrusted(s.name)} ({_untrusted(s.party)})" for s in request.submitters
        ),
        "vote_date": vote.date.isoformat(),
        "vote_outcome": vote.outcome,
        "votes_for": _format_parties(vote.for_),
        "votes_for_total": str(sum(v.seats for v in vote.for_)),
        "votes_against": _format_parties(vote.against),
        "votes_against_total": str(sum(v.seats for v in vote.against)),
        "topics": "\n".join(f"- {topic}" for topic in request.topics),
        "text_begin": TEXT_BEGIN,
        "text_end": TEXT_END,
        "text": _untrusted(request.text),
    }
    # One pass, so placeholders that happen to appear inside the motie text are not filled in.
    return PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


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


def run(request: SimplifyRequest, client=None) -> SimplifyResponse:
    """Writes the hook and detail text for one motie. Never raises: failures end up in `error`.

    `client` can be passed in to run without an API key (tests).
    """
    entry = None
    writer_prompt = ""
    try:
        # Writer only uses the first model for now.
        entry = load_models()[0]
        writer_prompt = build_writer_prompt(request)
        if client is None:
            client = client_for(entry)
        completion = client.chat.completions.create(
            model=entry.model,
            messages=[{"role": "user", "content": writer_prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        content = completion.choices[0].message.content or ""
        output = WriterOutput.model_validate(
            json.loads(content), context={"allowed_topics": request.topics}
        )
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
    except Exception as exc:
        return error_response(
            request.case_id, f"{type(exc).__name__}: {exc}", entry=entry, writer_prompt=writer_prompt
        )
