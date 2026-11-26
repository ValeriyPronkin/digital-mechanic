"""API страницы: список ТС, история, карточка через Mock ML."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from service import main
from service.clients import MLClient, ToirClient

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


def test_display_name_no_duplicate_make() -> None:
    names = {v["vehicle_id"]: v["name"] for v in client.get("/api/vehicles").json()}
    assert names["P456AT178"] == "МАЗ-5337"
    assert all(n for n in names.values())


def test_chat_and_ticket_endpoints(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from service.agent import Agent
    from service.store import Store
    from test_agent import ANOMALY, FixtureSearch, ScriptedLLM, c1_steps

    ag = Agent(ScriptedLLM(c1_steps(*ANOMALY)), ml, toir, FixtureSearch(), Store(":memory:"), main.fleet())
    monkeypatch.setattr(main, "agent", lambda: ag)
    r = client.post("/api/chat", json={"vehicle_id": ANOMALY[0], "session_id": ANOMALY[1], "message": "Оформи заявку"})
    assert r.status_code == 200
    data = r.json()
    assert data["draft"]["body"]["anomaly_type"] == "F02" and data["trace"]["steps"]
    bad = client.post("/api/tickets", json={"conversation_id": data["conversation_id"], "fingerprint": "nope"})
    assert bad.status_code == 409
    ok = client.post(
        "/api/tickets", json={"conversation_id": data["conversation_id"], "fingerprint": data["draft"]["fingerprint"]}
    )
    assert ok.status_code == 201 and ok.json()["ticket_id"].startswith("TKT-")


def test_ticket_unknown_conversation() -> None:
    r = client.post("/api/tickets", json={"conversation_id": "nope", "fingerprint": "x"})
    assert r.status_code == 404


def test_manual_pdf_missing() -> None:
    assert client.get("/manuals/doc-1").status_code == 404
