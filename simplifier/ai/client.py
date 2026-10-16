"""Builds an OpenAI-compatible client for one models.yaml entry."""

import os

from dotenv import load_dotenv
from openai import OpenAI

from .. import REPO_ROOT
from .registry import ModelEntry

# Symfony waits 120 s for the whole request, so a single call must stay well below that.
REQUEST_TIMEOUT_SECONDS = 60


def client_for(entry: ModelEntry) -> OpenAI:
    """Returns an `openai` client for this entry; the key comes from the environment or `.env`."""
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get(entry.api_key_env)
    if not api_key:
        raise RuntimeError(f"{entry.api_key_env} is not set (see .env.example)")
    # No retries inside the client: a failing model is handled by moving to the next one.
    return OpenAI(
        base_url=entry.base_url,
        api_key=api_key,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
