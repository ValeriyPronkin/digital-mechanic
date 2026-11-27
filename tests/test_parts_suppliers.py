"""Несколько поставщиков запчастей: каждый — свой файл настроек, опрос параллельно, упавший не валит остальных."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from service import api_v2, main
from service.clients import MLClient, ToirClient
from service.parts_supplier import (
    BY_NAME,
    CsvSupplier,
    HttpSupplier,
    Lookup,
    NoSupplier,
    Offer,
    SupplierSet,
    from_env,
    offers_for_parts,
)
from test_agent import ANOMALY, DRAFT, call, make_agent, say

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo" / "suppliers"
API_ITEMS = json.loads((ROOT / "data" / "demo" / "parts_api_demo.json").read_text(encoding="utf-8"))["items"]


def demo_api(req: httpx.Request) -> httpx.Response:
    """Та же выдача, что у заглушки `make parts-demo`, — без сети."""
    from service.parts_demo_api import search

    return httpx.Response(200, json=search(req.url.params["q"]))


def two_suppliers(monkeypatch: pytest.MonkeyPatch, transport: Any = demo_api) -> Any:
    monkeypatch.setenv("PARTS_SUPPLIERS", str(DEMO.relative_to(ROOT)))
    monkeypatch.setenv("PARTS_SUPPLIER", "none")  # новый список важнее прежней настройки
    return from_env(httpx.Client(transport=httpx.MockTransport(transport)))


def test_two_suppliers_side_by_side_sorted(monkeypatch: pytest.MonkeyPatch) -> None:
    sup = two_suppliers(monkeypatch)
    assert isinstance(sup, SupplierSet) and [n for n, _, _ in sup.suppliers] == [
        "Демо-склад (вымышленный)",
        "Демо-API (вымышленный)",
    ]
    r = sup.find("236-1007118")  # у обоих в наличии: сначала срок короче (склад, 1 дн.)
    assert [o.supplier for o in r.offers] == ["Демо-склад (вымышленный)", "Демо-API (вымышленный)"]
    assert [s.status for s in r.suppliers] == ["ok", "ok"]
    r = sup.find("236-1007186")  # на складе «под заказ», в API — есть: в наличии первым
    assert [o.supplier for o in r.offers] == ["Демо-API (вымышленный)", "Демо-склад (вымышленный)"]
    assert r.offers[0].in_stock is True and r.offers[1].in_stock is False
    view = r.public()
    assert {"supplier", "designation", "available", "in_stock", "price_rub", "lead_days", "url"} <= set(
        view["offers"][0]
    )


def test_sort_in_stock_then_lead_then_price() -> None:
    offers = [
        Offer(supplier="c", available="под заказ", lead_days=1, price_rub=1),
        Offer(supplier="b", available="есть", lead_days=3, price_rub=50),
        Offer(supplier="a", available="5 шт.", lead_days=3, price_rub=10),
        Offer(supplier="d", available=None, lead_days=0),
        Offer(supplier="e", available="0 шт.", lead_days=0),
    ]
    sup = SupplierSet([("x", _Fixed(offers), 1.0)])
    assert [o.supplier for o in sup.find("q").offers] == ["a", "b", "d", "e", "c"]  # нет в наличии — по сроку


class _Fixed:
    def __init__(self, offers: list[Offer], delay: float = 0.0, boom: bool = False) -> None:
        self.offers, self.delay, self.boom = offers, delay, boom

    def find(self, query: str) -> Lookup:
        time.sleep(self.delay)
        if self.boom:
            raise RuntimeError("сломался")
        return Lookup(connected=True, offers=[Offer(**o.__dict__) for o in self.offers])


def test_failed_or_slow_supplier_does_not_sink_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    down = two_suppliers(monkeypatch, lambda req: httpx.Response(503))
    r = down.find("236-1007118")
    assert [o.supplier for o in r.offers] == ["Демо-склад (вымышленный)"]
    assert [(s.name, s.status, s.note) for s in r.suppliers][1] == ("Демо-API (вымышленный)", "failed", "не ответил")

    good = _Fixed([Offer(designation="236-1007118", available="есть")])
    sup = SupplierSet(
        [("быстрый", good, 1.0), ("медленный", _Fixed([], delay=2.0), 0.2), ("упал", _Fixed([], boom=True), 1.0)]
    )
    t0 = time.monotonic()
    r = sup.find("236-1007118")
    assert time.monotonic() - t0 < 1.0  # медленного не ждём дольше его таймаута
    assert [o.supplier for o in r.offers] == ["быстрый"]
    st = {s.name: (s.status, s.note) for s in r.suppliers}
    assert st["медленный"] == ("failed", "не ответил за 0.2 с") and st["упал"][0] == "failed"

    gone = SupplierSet([("упал", _Fixed([], boom=True), 1.0)]).find("x")
    assert gone.connected and not gone.offers and "не ответили" in gone.note


def test_backward_compatible_single_supplier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARTS_SUPPLIERS", raising=False)
    monkeypatch.delenv("PARTS_SUPPLIER_CONFIG", raising=False)
    monkeypatch.setenv("PARTS_SUPPLIER", "csv")
    sup = from_env()
    assert isinstance(sup, CsvSupplier) and sup.find("236-1007118").offers[0].lead_days == 1
    monkeypatch.setenv("PARTS_SUPPLIER", "http")
    monkeypatch.setenv("PARTS_SUPPLIER_CONFIG", "data/demo/parts_supplier_http.example.json")
    assert isinstance(from_env(), HttpSupplier)
    monkeypatch.delenv("PARTS_SUPPLIER")
    assert isinstance(from_env(), NoSupplier)  # по умолчанию — «каталог не подключён»


def test_secret_only_from_env_and_disabled_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = json.loads((DEMO / "02-demo-api.json").read_text(encoding="utf-8"))
    assert all(str(v).startswith("env:") for v in cfg["headers"].values())  # в файле — только имя переменной
    (tmp_path / "a.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({**cfg, "supplier": "выключен", "enabled": False}), encoding="utf-8")
    monkeypatch.setenv("PARTS_SUPPLIERS", str(tmp_path))
    monkeypatch.setenv("DEMO_PARTS_API_TOKEN", "t-2")
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("Authorization", "")
        return httpx.Response(200, json={"items": []})

    sup = from_env(httpx.Client(transport=httpx.MockTransport(handler)))
    assert [n for n, _, _ in sup.suppliers] == ["Демо-API (вымышленный)"]  # type: ignore[attr-defined]
    assert sup.find("x").suppliers[0].status == "empty" and seen["auth"] == "t-2"


def test_designation_only_from_manual_else_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    sup = two_suppliers(monkeypatch)
    parts = ["Втулка коромысла (236-1007118), стр. 169", "Термостат (999-0000000), стр. 221"]
    out = offers_for_parts(sup, parts, {parts[0]: "236-1007118"})  # обозначение — из матрицы руководства
    a, b = out["items"]
    assert a["by"] == "designation" and a["query"] == "236-1007118" and a["check"] == "" and len(a["offers"]) == 2
    # обозначение в скобках написал не справочник руководства — не ищем по нему, только по названию, с пометкой
    assert b["by"] == "name" and b["query"] == "Термостат" and b["check"] == BY_NAME
    assert b["offers"][0]["name"] == "Термостат ЯМЗ-536 (демо-API)"
    assert offers_for_parts(NoSupplier(), parts) == {
        "connected": False,
        "note": NoSupplier().find("x").note,
        "items": [],
    }


def test_manual_designations_come_from_matrix() -> None:
    from service.fleet import fleet

    v = next(x for x in fleet().vehicles if x.engine_model == "ЯМЗ-236М2")
    conv = type("C", (), {"vehicle": v})()
    got = api_v2.manual_designations(conv, "F01")  # type: ignore[arg-type]
    assert got["Втулка коромысла (236-1007118), стр. 169"] == "236-1007118"


def test_v2_ticket_pending_carries_parts_offers(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    parts = ["Втулка коромысла (236-1007118), стр. 169", "термостат, стр. 221"]
    steps = [
        say("Давление масла на холостом ходу не менее 0,1 МПа [R1]."),
        call("search_manual", query="давление масла"),
        call("draft_ticket", **DRAFT, spare_parts=parts),
        say("Черновик заявки готов [R1]."),
    ]
    ag, _ = make_agent(steps, ml, toir)
    sup = two_suppliers(monkeypatch)
    app = main.FastAPI()
    router = api_v2.build_router(
        lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore(), get_parts=lambda: sup
    )
    app.include_router(router)
    c = TestClient(app)
    vid, sid = ANOMALY
    c.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Что с двигателем?"})
    r = c.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Создать заявку"})
    ev = [json.loads(x[6:]) for x in r.text.split("\n") if x.startswith("data: ")]
    pending = next(e for e in ev if e["type"] == "ticket_pending")
    po = pending["parts_offers"]
    assert po["connected"] and [i["index"] for i in po["items"]] == [0, 1]
    # у F02 этого двигателя в руководстве обозначения втулки нет — «(236-1007118)» написала модель: только по названию
    assert all(i["by"] == "name" and i["check"] == BY_NAME for i in po["items"])
    assert po["items"][1]["offers"][0]["supplier"] == "Демо-API (вымышленный)"
    ok = c.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid}).json()
    assert ok["parts_offers"] == po  # на карточке заявки — показанные предложения

    ag2, _ = make_agent(steps, ml, toir)
    off = api_v2.build_router(
        lambda: ag2, lambda: ag2.store, main.fleet, lambda r: None, api_v2.ThreadStore(), get_parts=NoSupplier
    )
    app2 = main.FastAPI()
    app2.include_router(off)
    c2 = TestClient(app2)
    c2.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Что с двигателем?"})
    r2 = c2.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Создать заявку"})
    p2 = next(json.loads(x[6:]) for x in r2.text.split("\n") if x.startswith("data: ") and "ticket_pending" in x)
    assert p2["parts_offers"]["connected"] is False and "не подключён" in p2["parts_offers"]["note"]  # честно
