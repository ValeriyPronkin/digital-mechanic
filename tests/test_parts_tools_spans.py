"""Разметка запчастей и инструмента в ответе /api/v2 (ночь 27→28.11, Валерий и Никита: отдельным цветом).
Размечает сервер по реестру `data/parts_tools.json`, а не модель: спаны {type, text, start, end, …} в событии text."""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from fastapi.testclient import TestClient

from service import api_v2, main, parts_tools
from service.clients import MLClient, ToirClient
from test_agent import make_agent, say
from test_api_v2 import events


def test_spans_mark_parts_and_tools_by_registry() -> None:
    text = "Замените уплотнительные кольца инжектора (6) и упорную шайбу инжектора [S1]. Ключом S=13 затянуть."
    sp = parts_tools.spans("ЯМЗ-536", text, {("yamz-536-rk", 152): "S1"})
    by_text = {s["text"]: s for s in sp}
    ring = by_text["уплотнительные кольца инжектора"]
    assert ring["type"] == "part" and ring["page"] == 152 and ring["ref"] == "S1"
    start, end = int(ring["start"]), int(ring["end"])  # type: ignore[call-overload]
    assert text[start:end] == "уплотнительные кольца инжектора"
    assert by_text["упорную шайбу инжектора"]["type"] == "part"  # в другом падеже — по основам слов
    key = by_text["Ключом S=13"]  # размер ключа — вместе со словом «ключ» (web-2, 27.11)
    assert key["type"] == "tool" and key["designation"] == "S=13" and key["page"] is None  # «S=13» — на многих стр.
    assert "Замените" not in by_text  # глагол — не деталь


def test_unique_designation_gets_its_page_and_no_overlaps() -> None:
    text = "Сектор 24-Ф-74784.001 и шаблон кулачка 24-Ф-74784.002."
    sp = parts_tools.spans("ЗМЗ-40904.10", text)
    codes = {s["text"]: s for s in sp if s["designation"]}
    assert codes["24-Ф-74784.001"]["type"] == "tool"
    assert codes["24-Ф-74784.001"]["page"] is None  # обозначение — на стр. 135, 199 и 210: страницу не выбираем
    gasket = parts_tools.spans("ЯМЗ-536", "Прокладка головки 536.1003206-10.")
    assert any(s["designation"] == "536.1003206-10" and s["page"] == 153 for s in gasket)  # одна страница
    ends = [(s["start"], s["end"]) for s in sp]
    assert all(e1 <= s2 for (_, e1), (s2, _) in pairwise(ends))  # без пересечений


def test_other_engine_registry_not_used() -> None:
    assert not [s for s in parts_tools.spans("ЯМЗ-236М2", "Сектор 24-Ф-74784.001") if s["designation"]]


def test_text_event_carries_spans(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Фазы проверяют сектором и шаблоном кулачка.")] * 2, ml, toir, prefetch=False)
    app = main.FastAPI()
    app.include_router(api_v2.build_router(lambda: ag, lambda: ag.store, main.fleet, lambda r: None,
                                           api_v2.ThreadStore()))  # fmt: skip
    r = TestClient(app).post("/api/v2/chat", json={"vehicle_id": "Y815BM178", "session_id": "S-0152",
                                                   "new_thread": True, "message": "Как проверить фазы?"})  # fmt: skip
    text: dict[str, Any] = next(e for e in events(r) if e["type"] == "text")
    assert {s["text"] for s in text["spans"] if s["type"] == "tool"} >= {"сектором", "шаблоном"}
    for s in text["spans"]:
        assert text["text"][s["start"] : s["end"]] == s["text"]
