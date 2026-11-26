"""Каркас отвечает: /health и страница. Проверка, что CI умеет падать: сломать assert → make check красный."""

import pytest
from fastapi.testclient import TestClient

from service.main import app

client = TestClient(app)


def test_health_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_hides_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test-value")
    body = client.get("/health").text
    assert "sk-test-value" not in body
    assert '"llm_key_present":true' in body


def test_index_page() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Сервис запущен" in resp.text
