"""Loads models.yaml: the ordered list of OpenAI-compatible endpoints to try."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .. import REPO_ROOT

MODELS_FILE = REPO_ROOT / "models.yaml"


class ModelEntry(BaseModel):
    name: str
    base_url: str
    model: str
    api_key_env: str
    # Requests per minute allowed by the provider; no limit is applied when left out.
    rpm: int | None = Field(default=None, ge=1)
    # Extra keyword arguments for chat.completions.create, e.g. max_tokens or reasoning_effort.
    options: dict[str, Any] = Field(default_factory=dict)

    @property
    def provider(self) -> str:
        """The part of `name` before the first dash, e.g. "mistral-small" -> "mistral"."""
        return self.name.split("-", 1)[0]


def load_models(path: Path = MODELS_FILE) -> list[ModelEntry]:
    """Returns the models in the order they should be tried."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = [ModelEntry.model_validate(entry) for entry in data.get("models") or []]
    if not models:
        raise ValueError(f"no models found in {path}")
    return models
