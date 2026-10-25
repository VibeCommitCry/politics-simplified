"""Builds the writer and critic prompts from prompts/<version>/ and the request.

All prompt text lives in prompts/<version>/*.md; this module only loads files, computes values
and joins parts:

- writer.md, critic.md: the fixed rules, read as-is.
- data.md: the request data block (shared by writer and critic).
- feedback.md: the writer's previous answer and the critic's problems (writer, from round 2).
- answer.md, critic_answer.md: the answer format for the writer and the critic.

Templates use string.Template placeholders:

- lowercase (`$title`, `$vote_date`, `$text`): runtime values computed here.
- UPPERCASE (`$HOOK`, `$PASSED`): JSON keys, taken from the OutputData / CriticData enums.

A literal `$` in a template is written `$$`. Substituted values are never re-scanned, so `$` or
`{}` in the request text is safe. A missing placeholder raises KeyError.
"""

from enum import Enum
from functools import cache
from string import Template

from .. import REPO_ROOT
from ..api.enums.critic_data import CriticData
from ..api.enums.output_data import OutputData
from ..api.schemas import PartyVote, SimplifyRequest, WriterOutput
from .sanitize import ANSWER_BEGIN, ANSWER_END, TEXT_BEGIN, TEXT_END, untrusted

PROMPT_VERSION = "v1"
PROMPTS_DIR = REPO_ROOT / "prompts"


def build_writer_prompt(
    request: SimplifyRequest,
    version: str = PROMPT_VERSION,
    previous: WriterOutput | None = None,
    problems: list[str] | None = None,
) -> str:
    """Joins writer.md, the data block filled from the request, and the answer format.

    From the second round on, `previous` and `problems` add the earlier answer and the critic's
    problems.
    """
    parts = [static(version, "writer"), render(version, "data", **_request_values(request))]
    if previous is not None:
        parts.append(
            render(
                version,
                "feedback",
                answer_begin=ANSWER_BEGIN,
                answer_end=ANSWER_END,
                previous=untrusted(previous.model_dump_json(indent=2)),
                problem_list="\n".join(f"- {untrusted(problem)}" for problem in problems or []),
            )
        )
    parts.append(render(version, "answer", **_keys(OutputData)))
    return "\n\n".join(parts) + "\n"


def build_critic_prompt(
    request: SimplifyRequest, output: WriterOutput, version: str = PROMPT_VERSION
) -> str:
    """Joins critic.md, the same data block, the writer's answer and the verdict format."""
    parts = [
        static(version, "critic"),
        render(version, "data", **_request_values(request)),
        render(
            version,
            "critic_answer",
            answer_begin=ANSWER_BEGIN,
            answer_end=ANSWER_END,
            answer=untrusted(output.model_dump_json(indent=2)),
            **_keys(CriticData),
        ),
    ]
    return "\n\n".join(parts) + "\n"


@cache
def _read(version: str, name: str) -> str:
    # Editors add a trailing newline; parts are joined explicitly instead.
    return (PROMPTS_DIR / version / f"{name}.md").read_text(encoding="utf-8").rstrip("\n")


def static(version: str, name: str) -> str:
    """A prompt file read as-is, without substitution."""
    return _read(version, name)


def render(version: str, name: str, **values: str) -> str:
    """Fills a template. A missing placeholder raises KeyError instead of becoming ''."""
    return Template(_read(version, name)).substitute(values)


def _keys(enum_cls: type[Enum]) -> dict[str, str]:
    return {member.name: str(member.value) for member in enum_cls}


def _request_values(request: SimplifyRequest) -> dict[str, str]:
    vote = request.vote
    return {
        "title": untrusted(request.title),
        "submitters": "\n".join(
            f"- {untrusted(s.name)} ({untrusted(s.party)})" for s in request.submitters
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
        "text": untrusted(request.text),
    }


def _format_parties(votes: list[PartyVote]) -> str:
    if not votes:
        return "- (geen partijen)"
    return "\n".join(
        f"- {untrusted(vote.party)}: {vote.seats} {'zetel' if vote.seats == 1 else 'zetels'}"
        for vote in votes
    )
