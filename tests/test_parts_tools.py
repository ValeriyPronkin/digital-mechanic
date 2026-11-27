"""Запчасти с обозначениями, инструмент к работам и поставщик запчастей (issue #10, п. 2; заказчик 26.11)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from matrix_fixture import needs_matrix
from service.clients import MLClient, ToirClient
from service.fault_matrix import Ref, all_cells, cell_for, ref_problem
from service.parts_supplier import NOT_CONNECTED, CsvSupplier, HttpSupplier, NoSupplier, from_env
from test_agent import call, first, make_agent, say

ROOT = Path(__file__).resolve().parents[1]


def _cell_with(pred: object) -> tuple[str, str]:
    """Проверка с отклонением, чья ячейка матрицы удовлетворяет условию."""

    def ok(v: object, s: object) -> bool:
        if getattr(s, "status", "") != "anomaly" or getattr(s, "signal_quality", "") == "bad":
            return False
        cell = cell_for(getattr(s, "anomaly_type", "") or "", getattr(v, "engine_model", ""))
        return cell is not None and cell.status == "confirmed" and pred(cell)  # type: ignore[operator]

    return first(ok)


def test_designation_must_be_in_quote_and_tools_on_page() -> None:
    page = {("yamz-236-re", 169): "Втулка коромысла 236-1007118 Втулка толкателя 236-1007186. Щуп 0,25 мм"}
    text = page.get
    good = Ref("yamz-236-re", 169, "Втулка коромысла 236-1007118", designation="236-1007118")
    assert ref_problem(good, "ЯМЗ-236М2", lambda d, p: text((d, p))) is None
    bad = Ref("yamz-236-re", 169, "Втулка коромысла", designation="236-1007118")
    assert "обозначения" in (ref_problem(bad, "ЯМЗ-236М2", lambda d, p: text((d, p))) or "")
    tool = Ref("yamz-236-re", 169, "Втулка толкателя 236-1007186", tools=["съёмник И-801"])
    assert "инструмента нет" in (ref_problem(tool, "ЯМЗ-236М2", lambda d, p: text((d, p))) or "")
    assert good.part_name == "Втулка коромысла"


@needs_matrix
def test_matrix_has_designations_and_tools() -> None:
    conf = [c for c in all_cells() if c.status == "confirmed"]
    assert any(p.designation for c in conf for p in c.spare_parts)
    assert any(o.tools for c in conf for o in c.operations)
    for c in conf:
        for p in c.spare_parts:
            assert not p.designation or p.designation in p.quote


@needs_matrix
def test_draft_lists_parts_with_designation_and_tools(ml: MLClient, toir: ToirClient) -> None:
    vid, sid = _cell_with(lambda c: any(p.designation for p in c.spare_parts) or any(o.tools for o in c.operations))
    ag, _ = make_agent([call("draft_ticket", conclusion="Отклонение по проверке"), say("Черновик готов.")], ml, toir)
    reply = ag.ask(ag.start(vid, sid), "Оформи заявку")
    assert reply.draft is not None
    cell = cell_for(reply.draft["body"]["anomaly_type"], ag.fleet.vehicle(vid).engine_model)  # type: ignore[union-attr]
    assert cell is not None
    parts = reply.draft["body"]["spare_parts"]
    for p in cell.spare_parts:
        if p.designation:
            assert f"{p.part_name} ({p.designation}), стр. {p.page}" in parts
    tools = {t for o in cell.operations for t in o.tools}
    assert set(reply.draft["tools"]) == tools


def test_no_supplier_is_honest() -> None:
    r = NoSupplier().find("236-1007118")
    assert not r.connected and r.note == NOT_CONNECTED and not r.offers


def test_csv_supplier_from_config_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTS_SUPPLIER", "csv")
    monkeypatch.delenv("PARTS_SUPPLIER_CONFIG", raising=False)
    sup = from_env()
    assert isinstance(sup, CsvSupplier)
    r = sup.find("236 1007118")  # обозначение без дефиса — тоже найдётся
    assert r.connected and r.offers[0].designation == "236-1007118" and r.offers[0].lead_days == 1
    assert "вымышлен" in r.offers[0].supplier.lower()  # type: ignore[union-attr]
    assert sup.find("турбокомпрессор").offers[0].designation == "53602.1118010-10"  # по наименованию
    assert not sup.find("999-9999999").offers


def test_demo_price_is_marked_fictional() -> None:
    head = (ROOT / "data" / "demo" / "parts_prices_demo.csv").read_text(encoding="utf-8").splitlines()[0]
    assert head.startswith("#") and "ВЫМЫШЛЕННЫЕ" in head


def test_http_supplier_maps_fields_and_survives_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = json.loads((ROOT / "data" / "demo" / "parts_supplier_http.example.json").read_text(encoding="utf-8"))
    monkeypatch.setenv("PARTS_SUPPLIER_TOKEN", "t-1")
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("Authorization", "")
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"items": [{"article": "236-1007118", "title": "Втулка", "price": "99,5"}]})

    sup = HttpSupplier(cfg, httpx.Client(transport=httpx.MockTransport(handler)))
    r = sup.find("236-1007118")
    assert r.offers[0].price_rub == 99.5 and r.offers[0].available is None  # поля необязательные
    assert seen["auth"] == "t-1" and "q=236-1007118" in seen["url"]
    down = HttpSupplier(cfg, httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503))))
    assert down.find("x").offers == [] and "не ответил" in down.find("x").note


def test_parts_api_default_not_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from service import main

    monkeypatch.delenv("PARTS_SUPPLIER", raising=False)
    main.parts_supplier.cache_clear()
    r = TestClient(main.app).get("/api/parts", params={"q": "236-1007118"}).json()
    assert r["connected"] is False and "не подключён" in r["note"]


INDEX = Path(os.environ.get("INDEX_DIR", ".index"))


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_parts_and_tools_on_their_pages_in_real_index() -> None:
    from service.manual_search import default_searcher

    page_text = getattr(default_searcher(), "page_text", None)
    for c in all_cells():
        for r in [*c.spare_parts, *c.operations]:
            if r.designation or r.tools:
                assert ref_problem(r, c.engine, page_text) is None, (c.code, c.engine, r)
