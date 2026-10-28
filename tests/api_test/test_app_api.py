"""The HTTP endpoint with fake model clients. Needs no API key."""

import json

import pytest
from fastapi.testclient import TestClient

from simplifier.api import app_api
from simplifier.core import pipeline
from tests.fakes import SAMPLE, FakeClient, entry

KEY = "test-secret"
AUTH = {"X-Api-Key": KEY}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(app_api.API_KEY_ENV, KEY)
    fake = FakeClient()
    monkeypatch.setattr(
        app_api,
        "run",
        lambda request: pipeline.run(request, [entry("first-model")], lambda e: fake),
    )
    return TestClient(app_api.app)


def sample_body():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def test_health_reports_ok_without_a_key(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_simplify_returns_the_pipeline_response(client):
    body = sample_body()

    response = client.post("/simplify", json=body, headers=AUTH)

    assert response.status_code == 200
    data = response.json()
    assert data["error"] is None
    assert data["critic_passed"] is True
    assert data["case_id"] == body["case_id"]


def test_invalid_body_gets_an_error_response_with_the_case_id(client):
    response = client.post("/simplify", json={"case_id": "x"}, headers=AUTH)

    assert response.status_code == 422
    data = response.json()
    assert data["case_id"] == "x"
    assert data["critic_passed"] is False
    assert data["error"].startswith("invalid request:")


def test_body_that_is_not_an_object_still_gets_an_error_response(client):
    response = client.post("/simplify", json=["not", "an", "object"], headers=AUTH)

    assert response.status_code == 422
    data = response.json()
    assert data["case_id"] == ""
    assert data["critic_passed"] is False
    assert data["error"]


@pytest.mark.parametrize("headers", [{}, {"X-Api-Key": "wrong"}, {"X-Api-Key": ""}])
def test_missing_or_wrong_key_gets_a_401_error_response(client, headers):
    response = client.post("/simplify", json=sample_body(), headers=headers)

    assert response.status_code == 401
    data = response.json()
    assert data["critic_passed"] is False
    assert data["error"].startswith("unauthorized:")


def test_key_is_checked_before_the_body(client):
    response = client.post("/simplify", json={"case_id": "x"})

    assert response.status_code == 401


def test_service_refuses_to_start_without_the_key(monkeypatch):
    monkeypatch.delenv(app_api.API_KEY_ENV, raising=False)
    # Stops load_dotenv from putting a key from a local .env back.
    monkeypatch.setattr(app_api, "load_dotenv", lambda *_: None)

    with pytest.raises(RuntimeError, match=app_api.API_KEY_ENV):
        with TestClient(app_api.app):
            pass


def test_service_starts_with_the_key(client):
    with TestClient(app_api.app) as started:
        assert started.get("/health").status_code == 200
