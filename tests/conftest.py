"""Fixtures shared by every test folder."""

import json

import pytest

from simplifier import limits
from simplifier.api.schemas import SimplifyRequest
from tests.fakes import SAMPLE


@pytest.fixture(autouse=True)
def clean_state():
    limits.reset_state()
    yield
    limits.reset_state()


@pytest.fixture
def request_():
    return SimplifyRequest.model_validate(json.loads(SAMPLE.read_text(encoding="utf-8")))
