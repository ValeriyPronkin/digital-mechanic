"""API страницы: список ТС, история, карточка через Mock ML."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from service import main
from service.clients import MLClient

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _use_mock(ml: MLClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "ml_client", lambda: ml)


def test_vehicles_list() -> None:
    vs = client.get("/api/vehicles").json()
    assert len(vs) == 50
    assert all(v["engine_model"] and v["garage_no"] for v in vs)
    assert any(v["model"] is None for v in vs)


def test_history_newest_first() -> None:
    h = client.get("/api/vehicles/M333YK47").json()
    times = [s["checked_at"] for s in h["sessions"]]
    assert times == sorted(times, reverse=True)
    assert "status" not in h["sessions"][0]


def test_history_404() -> None:
    assert client.get("/api/vehicles/NOPE").status_code == 404


def test_diagnose_card() -> None:
    card = client.post("/api/diagnose", json={"vehicle_id": "M333YK47", "session_id": "S-0005"}).json()
    assert card["status"] == "anomaly" and card["ticket_possible"] is True


def test_diagnose_unknown_session() -> None:
    r = client.post("/api/diagnose", json={"vehicle_id": "M333YK47", "session_id": "S-0001"})
    assert r.status_code == 404 and "не найдена" in r.json()["detail"]
