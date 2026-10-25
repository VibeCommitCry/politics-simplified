"""Fake model clients and model entries, so the pipeline runs without an API key."""

import json
from pathlib import Path
from types import SimpleNamespace

from simplifier.ai.registry import ModelEntry

SAMPLE = Path(__file__).parent / "samples" / "input-example.json"

GOOD_ANSWER = {
    "hook": "Moet je huur een jaar gelijk blijven?",
    "detail": {
        "waar_gaat_het_over": "a",
        "wat_betekent_het_voor_jou": "b",
        "wat_is_er_besloten": "c",
        "moeilijke_woorden": [],
    },
    "topics": ["Wonen"],
    "relevance": 4,
}

PASS_VERDICT = {"passed": True, "confidence": 0.9, "problems": []}

CRITIC_PROMPT_MARK = "## Het antwoord van de schrijver"


class FakeStatusError(Exception):
    """Looks like openai.APIStatusError: the pipeline only reads `status_code`."""

    def __init__(self, status_code: int, code: str | None = None, body: dict | None = None):
        super().__init__(f"Error code: {status_code}")
        self.status_code = status_code
        self.code = code
        self.body = body


def fail_verdict(*problems: str) -> str:
    return json.dumps({"passed": False, "confidence": 0.4, "problems": list(problems)})


class FakeClient:
    """Writer calls work through `failures` first (one per call), then return a good answer.
    Critic calls work through `verdicts` the same way, then pass.

    A failure or verdict is an exception to raise, or a string to return as the model's text.
    `calls` counts writer calls only; critic calls are in `critic_calls`.
    """

    def __init__(self, failures=(), verdicts=()):
        self.failures = list(failures)
        self.verdicts = list(verdicts)
        self.calls = 0
        self.critic_calls = 0
        self.last_arguments = {}
        self.writer_prompts = []
        self.critic_arguments = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        if CRITIC_PROMPT_MARK in prompt:
            self.critic_calls += 1
            self.critic_arguments = kwargs
            return self._answer(self.verdicts, json.dumps(PASS_VERDICT))
        self.calls += 1
        self.last_arguments = kwargs
        self.writer_prompts.append(prompt)
        return self._answer(self.failures, json.dumps(GOOD_ANSWER))

    @staticmethod
    def _answer(queue, default):
        content = default
        if queue:
            failure = queue.pop(0)
            if isinstance(failure, Exception):
                raise failure
            content = failure
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def entry(name: str, **extra) -> ModelEntry:
    return ModelEntry(
        name=name, base_url="http://fake", model=f"{name}-model", api_key_env="NONE", **extra
    )
