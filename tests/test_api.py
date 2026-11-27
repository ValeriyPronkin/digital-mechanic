"""API страницы: список ТС, история, карточка через Mock ML."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from matrix_fixture import needs_matrix
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


def _agent(ml: MLClient, toir: ToirClient, steps: list[Any]) -> Any:
    from service.agent import Agent
    from service.store import Store
    from test_agent import FixtureSearch, ScriptedLLM

    return Agent(ScriptedLLM(steps), ml, toir, FixtureSearch(), Store(":memory:"), main.fleet(), plan_search=False)


def test_chat_and_ticket_survive_instance_switch(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Вопрос и «Отправить» попадают в разные экземпляры (разные Agent и Store) — заявка всё равно уходит."""
    from test_agent import ANOMALY, call, say

    vid, sid = ANOMALY
    first = _agent(ml, toir, [call("get_diagnosis", vehicle_id=vid, session_id=sid), say("Это F02.")])
    monkeypatch.setattr(main, "agent", lambda: first)
    r1 = client.post("/api/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Что случилось?"}).json()

    second = _agent(
        ml,
        toir,
        [
            call("search_manual", query="масло"),
            call(
                "draft_ticket",
                conclusion="Низкое давление масла",
                operations=[{"text": "Замерить давление масла", "ref": "R1"}],
            ),
            say("Черновик готов [R1]"),
        ],
    )
    monkeypatch.setattr(main, "agent", lambda: second)
    r2 = client.post(
        "/api/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Оформи заявку", "state": r1["state"]}
    ).json()
    assert r2["conversation_id"] == r1["conversation_id"]
    seen = second.provider.seen[0]  # type: ignore[attr-defined]
    assert any(m["role"] == "tool" and m["name"] == "get_diagnosis" for m in seen)  # история пришла из state

    third = _agent(ml, toir, [])
    monkeypatch.setattr(main, "agent", lambda: third)
    bad = client.post("/api/tickets", json={"state": r2["state"], "fingerprint": "nope"})
    assert bad.status_code == 409
    ok = client.post("/api/tickets", json={"state": r2["state"], "fingerprint": r2["draft"]["fingerprint"]})
    assert ok.status_code == 201 and ok.json()["ticket_id"].startswith("TKT-")
    again = client.post("/api/tickets", json={"state": r2["state"], "fingerprint": r2["draft"]["fingerprint"]})
    assert again.status_code == 409 and "уже отправлена" in again.json()["detail"]


def test_tampered_state_rejected(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64
    import zlib

    from test_agent import ANOMALY, say

    monkeypatch.setattr(main, "agent", lambda: _agent(ml, toir, [say("ok")]))
    r = client.post("/api/chat", json={"vehicle_id": ANOMALY[0], "session_id": ANOMALY[1], "message": "?"}).json()
    blob = base64.urlsafe_b64decode(r["state"])
    raw = zlib.decompress(blob[16:]).replace(b"ok", b"OK")
    forged = base64.urlsafe_b64encode(blob[:16] + zlib.compress(raw)).decode()
    resp = client.post("/api/tickets", json={"state": forged, "fingerprint": "x"})
    assert resp.status_code == 400
    assert client.post("/api/tickets", json={"state": "мусор", "fingerprint": "x"}).status_code == 400


def test_chat_rate_limited(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from service.rate_limit import RateLimiter
    from test_agent import ANOMALY, say

    monkeypatch.setattr(main, "agent", lambda: _agent(ml, toir, [say("ok")] * 5))
    monkeypatch.setattr(main, "limiter", lambda: lim)
    lim = RateLimiter(per_client=2, total=100)
    body = {"vehicle_id": ANOMALY[0], "session_id": ANOMALY[1], "message": "?"}
    h = {"X-Forwarded-For": "6.6.6.6, 10.0.0.1"}
    assert client.post("/api/chat", json=body, headers=h).status_code == 200
    assert client.post("/api/chat", json=body, headers=h).status_code == 200
    third = client.post("/api/chat", json=body, headers=h)
    assert third.status_code == 429 and int(third.headers["retry-after"]) > 0
    other = client.post("/api/chat", json=body, headers={"X-Forwarded-For": "6.6.6.6, 10.0.0.2"})
    assert other.status_code == 200  # клиент — последний адрес, его дописал прокси


def test_ticket_requires_state() -> None:
    assert client.post("/api/tickets", json={"fingerprint": "x"}).status_code == 422


def test_manual_pdf_missing() -> None:
    assert client.get("/manuals/doc-1").status_code == 404


@needs_matrix
def test_anomaly_card_explains_from_matrix_without_model() -> None:
    """Пояснение к отклонению — из матрицы по руководству этого двигателя, без вызова модели (#16)."""
    from service.fault_matrix import cell_for
    from service.fleet import fleet
    from service.manuals.catalog import documents_for_engine

    for v in fleet().vehicles:
        s = next((s for s in v.sessions if s.status == "anomaly" and s.anomaly_type), None)
        cell = cell_for(s.anomaly_type, v.engine_model) if s and s.anomaly_type else None
        if s and cell and cell.status == "confirmed" and s.signal_quality == "good":
            break
    card = client.post("/api/diagnose", json={"vehicle_id": v.vehicle_id, "session_id": s.session_id}).json()
    m = card["manual"]
    assert m["status"] == "confirmed" and m["steps"]
    own = {d.designation for d in documents_for_engine(v.engine_model)}
    assert {st["manual"] for st in m["steps"]} <= own
    assert all(st["url"].startswith("/manuals/") for st in m["steps"])


def test_normal_card_has_no_manual_block() -> None:
    card = client.post("/api/diagnose", json={"vehicle_id": "M333YK47", "session_id": "S-0005"}).json()
    if card["status"] != "anomaly":
        assert card["manual"] is None
