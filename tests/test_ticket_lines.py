"""Страница каждой работы и запчасти заявки (лист заявки, карточка, печать) и реестр заявок главного механика.

Страницы идут рядом с телом заявки, а не в нём: в ТОиР уходит ровно схема `openapi_toir.json`."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from service import api_v2, main
from service.clients import MLClient, TicketRequest, ToirClient
from service.fault_matrix import cell_for
from service.verdict_policy import CONFIDENCE_LOW
from test_agent import ANOMALY, DRAFT, call, make_agent, say

TOIR_SCHEMA = json.loads(open("vendor/neurodvs_mock/openapi_toir.json", encoding="utf-8").read())
MATRIX_CHECK = ("B418HK98", "S-0008")  # F01 на ЯМЗ-236М2: проверенная ячейка матрицы, работы и запчасти


class RecordingToir(ToirClient):
    def __init__(self, inner: ToirClient) -> None:
        self.inner, self.bodies = inner, []

    def create_ticket(self, body: TicketRequest) -> Any:
        self.bodies.append(body.model_dump())
        return self.inner.create_ticket(body)


def events(resp: Any) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in resp.text.split("\n") if line.startswith("data: ")]


def client(steps: list[Any], ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> Any:
    rec = RecordingToir(toir)
    ag, _ = make_agent(steps, ml, rec)
    store = ag.store
    monkeypatch.setattr(main, "agent", lambda: ag)
    monkeypatch.setattr(main, "store", lambda: store)
    main.limiter.cache_clear()
    app = main.FastAPI()
    app.include_router(api_v2.build_router(lambda: ag, lambda: store, main.fleet, lambda r: None, api_v2.ThreadStore()))
    return TestClient(app), rec, store


def ask(c: TestClient, vid: str, sid: str, message: str, new: bool = False) -> list[dict[str, Any]]:
    body = {"vehicle_id": vid, "session_id": sid, "message": message, "new_thread": new}
    return events(c.post("/api/v2/chat", json=body))


def test_each_work_carries_its_page_and_the_toir_body_does_not(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [
        say("Давление масла на холостом ходу не менее 0,1 МПа [R1]."),
        call("search_manual", query="давление масла"),
        call("draft_ticket", **DRAFT),
        say("Черновик заявки готов [R1]."),
    ]
    c, rec, store = client(steps, ml, toir, monkeypatch)
    vid, sid = ANOMALY
    first = ask(c, vid, sid, "Что с двигателем?", new=True)
    verdict = next(e["block"] for e in first if e["type"] == "tool_result" and e.get("block"))
    assert verdict["confidence_threshold"] == CONFIDENCE_LOW  # порог правила кода — числом на карточке

    pending = next(e for e in ask(c, vid, sid, "Создать заявку на дефектовку") if e["type"] == "ticket_pending")
    op = pending["operations"][0]
    assert op["text"] == DRAFT["operations"][0]["text"]
    assert (op["manual_id"], op["pdf_page"], op["manual"]) == ("doc-1", 42, "Руководство по ремонту")
    assert op["source"].startswith("S") and op["short"]
    assert pending["payload"]["references"] == [{"manual": "Руководство по ремонту", "pdf_page": 42}]

    view = c.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid}).json()
    # в ТОиР — только поля контракта, ни одной страницы у работ
    request_schema = TOIR_SCHEMA["components"]["schemas"]["TicketRequest"]
    assert set(rec.bodies[0]) == set(request_schema["properties"])
    assert rec.bodies[0]["operations"] == [op["text"]]
    assert view["payload"] == rec.bodies[0]
    assert view["lines"]["operations"] == [op] and view["lines"]["spare_parts"] == []
    # и после перезагрузки: список заявок машины и сохранённая нить
    assert c.get(f"/api/v2/vehicles/{vid}/tickets").json()[0]["lines"] == view["lines"]
    thread = c.get(f"/api/v2/threads/current?vehicle_id={vid}").json()
    assert thread["transcript"][-1]["ticket"]["lines"] == view["lines"]

    # заявка, сохранённая до строк со страницами, читается: lines — null
    store._exec("UPDATE tickets SET lines=NULL")
    assert c.get(f"/api/v2/vehicles/{vid}/tickets").json()[0]["lines"] is None


def test_works_and_parts_from_the_matrix_carry_their_pages(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [
        say("Ответ по руководству."),
        call("draft_ticket", conclusion="Неисправность по результату проверки"),  # работы и запчасти — из матрицы
        say("Черновик заявки готов."),
    ]
    c, rec, _ = client(steps, ml, toir, monkeypatch)
    vid, sid = MATRIX_CHECK
    ask(c, vid, sid, "Что с двигателем?", new=True)
    pending = next(e for e in ask(c, vid, sid, "Создать заявку") if e["type"] == "ticket_pending")
    ops, parts = pending["operations"], pending["spare_parts"]
    assert ops and parts
    cell = cell_for("F01", "ЯМЗ-236М2")
    assert cell is not None
    assert [(o["manual_id"], o["pdf_page"]) for o in ops] == [(o.doc, o.page) for o in cell.operations]
    assert [(p["manual_id"], p["pdf_page"]) for p in parts] == [(p.doc, p.page) for p in cell.spare_parts]
    refs = {(r["manual"], r["pdf_page"]) for r in pending["payload"]["references"]}
    for line in ops:
        assert line["source"].startswith("S")  # страница открывается из листа заявки
        assert (line["manual"], line["pdf_page"]) in refs  # та же страница, что в references заявки
    for line in parts:
        assert line["source"].startswith("S") and line["manual"]

    # механик убрал запчасти: в сохранённых строках их нет, в ТОиР — тоже
    view = c.post(
        f"/api/v2/tickets/{pending['pending_id']}/approve",
        json={"vehicle_id": vid, "keep_operations": [0], "keep_spare_parts": []},
    ).json()
    assert rec.bodies[0]["spare_parts"] == [] and view["lines"]["spare_parts"] == []
    assert view["lines"]["operations"] == ops[:1]  # оставлена только первая работа (keep_operations=[0])


def test_the_register_lists_every_ticket_of_the_fleet(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [
        say("Давление масла на холостом ходу не менее 0,1 МПа [R1]."),
        call("search_manual", query="давление масла"),
        call("draft_ticket", **DRAFT),
        say("Черновик заявки готов [R1]."),
    ]
    c, _, _ = client(steps, ml, toir, monkeypatch)
    assert c.get("/api/v2/tickets").json() == []
    vid, sid = ANOMALY
    ask(c, vid, sid, "Что с двигателем?", new=True)
    pending = next(e for e in ask(c, vid, sid, "Создать заявку") if e["type"] == "ticket_pending")
    view = c.post(
        f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid, "urgency": "medium"}
    ).json()
    c.post(f"/api/v2/tickets/{view['id']}/outcome", json={"outcome": "other_fault", "note": "Течь сальника"})

    [row] = c.get("/api/v2/tickets").json()
    v = main.fleet().vehicle(vid)
    assert v is not None
    session = next(s for s in v.sessions if s.session_id == sid)
    assert row["ticket_id"] == view["ticket_id"] and row["session_id"] == sid
    assert (row["garage_no"], row["engine_model"], row["checked_at"]) == (
        v.garage_no,
        v.engine_model,
        session.checked_at,
    )
    assert row["fault_title"] == main.fleet().fault_titles[session.anomaly_type or ""]
    assert (row["urgency_proposed"], row["payload"]["urgency"]) == ("high", "medium")
    assert (row["outcome"], row["outcome_note"]) == ("other_fault", "Течь сальника")
    assert row["created_at"] and row["lines"]["operations"][0]["pdf_page"] == 42
