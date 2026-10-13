"""Loads models.yaml and builds an OpenAI-compatible client for one entry."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_FILE = REPO_ROOT / "models.yaml"

# Symfony waits 120 s for the whole request, so a single call must stay well below that.
REQUEST_TIMEOUT_SECONDS = 60


class ModelEntry(BaseModel):
    name: str
    base_url: str
    model: str
    api_key_env: str

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


def client_for(entry: ModelEntry) -> OpenAI:
    """Returns an `openai` client for this entry; the key comes from the environment or `.env`."""
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get(entry.api_key_env)
    if not api_key:
        raise RuntimeError(f"{entry.api_key_env} is not set (see .env.example)")
    return OpenAI(base_url=entry.base_url, api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
