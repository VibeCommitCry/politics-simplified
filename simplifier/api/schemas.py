"""Pydantic models for the /simplify contract and the rules that are checked in code."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

HOOK_MAX_CHARS = 200
MAX_TOPICS = 3


# --- Request -----------------------------------------------------------------


class Submitter(BaseModel):
    name: str
    party: str


class PartyVote(BaseModel):
    party: str
    seats: int = Field(ge=0)


class Vote(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date: date
    outcome: Literal["aangenomen", "verworpen"]
    # "for" is a Python keyword, so the JSON name is kept as an alias.
    for_: list[PartyVote] = Field(alias="for")
    against: list[PartyVote]


class SimplifyRequest(BaseModel):
    case_id: str
    title: str
    text: str = Field(min_length=1)
    submitters: list[Submitter] = Field(min_length=1)
    vote: Vote
    topics: list[str] = Field(min_length=1)
    related: list[str] = Field(default_factory=list)


# --- Writer output and response ----------------------------------------------


class DifficultWord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    woord: str = Field(min_length=1)
    betekenis: str = Field(min_length=1)


class Detail(BaseModel):
    """Exactly these four sections; anything else from the model is rejected."""

    model_config = ConfigDict(extra="forbid")

    waar_gaat_het_over: str = Field(min_length=1)
    wat_betekent_het_voor_jou: str = Field(min_length=1)
    wat_is_er_besloten: str = Field(min_length=1)
    moeilijke_woorden: list[DifficultWord]


class WriterOutput(BaseModel):
    """What the writer model must return.

    Validate with `context={"allowed_topics": request.topics}` so that topics
    outside the request's list are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    hook: str = Field(min_length=1, max_length=HOOK_MAX_CHARS)
    detail: Detail
    topics: list[str] = Field(min_length=1, max_length=MAX_TOPICS)
    relevance: int = Field(ge=1, le=5)

    @field_validator("topics")
    @classmethod
    def topics_come_from_request(cls, topics: list[str], info: ValidationInfo) -> list[str]:
        allowed = (info.context or {}).get("allowed_topics")
        if allowed is not None:
            unknown = [topic for topic in topics if topic not in allowed]
            if unknown:
                raise ValueError(f"topics not in the request's topic list: {unknown}")
        return topics


class CriticOutput(BaseModel):
    """What the critic model must return. `passed` and `problems` must agree."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    confidence: float = Field(ge=0, le=1)
    problems: list[str]

    @model_validator(mode="after")
    def passed_matches_problems(self) -> "CriticOutput":
        if self.passed and self.problems:
            raise ValueError("passed is true but problems were listed")
        if not self.passed and not self.problems:
            raise ValueError("passed is false but no problems were listed")
        return self


class Readability(BaseModel):
    before: float
    after: float


class Prompts(BaseModel):
    writer: str = ""
    critic: str = ""


class SimplifyResponse(BaseModel):
    """The response Symfony stores.

    When `error` is set the content fields are empty (hook "", detail null,
    topics [], relevance null) and `critic_passed` is false. Without an error
    they must all be filled.
    """

    case_id: str
    hook: str = Field(default="", max_length=HOOK_MAX_CHARS)
    detail: Detail | None = None
    topics: list[str] = Field(default_factory=list, max_length=MAX_TOPICS)
    relevance: int | None = Field(default=None, ge=1, le=5)
    critic_passed: bool = False
    confidence: float = Field(default=0.0, ge=0, le=1)
    rounds: int = Field(default=0, ge=0)
    critic_problems: list[str] = Field(default_factory=list)
    readability: Readability | None = None
    model: str = ""
    provider: str = ""
    prompt_version: str
    prompts: Prompts = Field(default_factory=Prompts)
    error: str | None = None

    @model_validator(mode="after")
    def content_or_error(self) -> "SimplifyResponse":
        if self.error is not None:
            if self.critic_passed:
                raise ValueError("critic_passed must be false when error is set")
            return self
        if not self.hook or self.detail is None or not self.topics or self.relevance is None:
            raise ValueError("hook, detail, topics and relevance are required when there is no error")
        return self
