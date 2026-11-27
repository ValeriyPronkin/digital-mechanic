"""Стенд без матрицы «код × двигатель» (#96, шаг 2): индекс выложен без неё или ещё старой версией.

Матрица — вне git и приходит из бакета вместе с индексом. Пока её нет, сервис не падает: /health говорит
`fault_matrix.present = false`, карточки отдаются без пояснения из руководства, правило 5 («узла нет — заявки нет»)
держится по источнику матрицы, агент работает через поиск по руководству.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from service import fault_matrix, main
from service.agent import TicketRefusedError
from service.clients import MLClient, ToirClient
from service.fleet import fleet
from test_agent import ANOMALY, INCOMPATIBLE, c1_steps, make_agent


@pytest.fixture(autouse=True)
def _no_matrix(ml: MLClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fault_matrix, "DATA_MATRIX_PATH", tmp_path / "нет" / "fault_matrix.json")
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setattr(main, "ml_client", lambda: ml)
    assert not fault_matrix.matrix_loaded()


def test_health_says_matrix_missing() -> None:
    body = TestClient(main.app).get("/health").json()
    assert body["status"] == "ok" and body["fault_matrix"] == {"present": False}


def test_every_anomaly_card_without_matrix() -> None:
    client = TestClient(main.app, raise_server_exceptions=False)
    seen = 0
    for v in fleet().vehicles:
        for s in v.sessions:
            if s.status != "anomaly":
                continue
            r = client.post("/api/diagnose", json={"vehicle_id": v.vehicle_id, "session_id": s.session_id})
            assert r.status_code == 200, (v.vehicle_id, s.session_id, r.status_code)
            card: dict[str, Any] = r.json()
            assert card.get("manual") is None  # пояснения из руководства нет — не выдумываем
            seen += 1
    assert seen > 0


def test_incompatible_still_refuses_ticket(ml: MLClient, toir: ToirClient) -> None:
    card = (
        TestClient(main.app)
        .post("/api/diagnose", json={"vehicle_id": INCOMPATIBLE[0], "session_id": INCOMPATIBLE[1]})
        .json()
    )
    assert card["compatible"] is False and card["ticket_possible"] is False
    ag, _ = make_agent(c1_steps(*INCOMPATIBLE), ml, toir)
    conv = ag.start(*INCOMPATIBLE)
    reply = ag.ask(conv, "Оформи заявку")
    if reply.draft is not None:
        with pytest.raises(TicketRefusedError):
            ag.confirm_ticket(conv, reply.draft["fingerprint"])


def test_c1_ticket_through_search_without_matrix(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent(c1_steps(*ANOMALY), ml, toir)
    conv = ag.start(*ANOMALY)
    reply = ag.ask(conv, "Оформи заявку")
    assert reply.draft is not None
    assert ag.confirm_ticket(conv, reply.draft["fingerprint"]).ticket_id.startswith("TKT-")
