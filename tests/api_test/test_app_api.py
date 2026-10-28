"""The HTTP endpoint with fake model clients. Needs no API key."""

import json

import pytest
from fastapi.testclient import TestClient

from simplifier.api import app_api
from simplifier.core import pipeline
from tests.fakes import SAMPLE, FakeClient, entry


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(
        app_api,
        "run",
        lambda request: pipeline.run(request, [entry("first-model")], lambda e: fake),
    )
    return TestClient(app_api.app)


def test_simplify_returns_the_pipeline_response(client):
    body = json.loads(SAMPLE.read_text(encoding="utf-8"))

    response = client.post("/simplify", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["error"] is None
    assert data["critic_passed"] is True
    assert data["case_id"] == body["case_id"]


def test_invalid_body_gets_an_error_response_with_the_case_id(client):
    response = client.post("/simplify", json={"case_id": "x"})

    assert response.status_code == 422
    data = response.json()
    assert data["case_id"] == "x"
    assert data["critic_passed"] is False
    assert data["error"].startswith("invalid request:")


def test_body_that_is_not_an_object_still_gets_an_error_response(client):
    response = client.post("/simplify", json=["not", "an", "object"])

    assert response.status_code == 422
    data = response.json()
    assert data["case_id"] == ""
    assert data["critic_passed"] is False
    assert data["error"]
