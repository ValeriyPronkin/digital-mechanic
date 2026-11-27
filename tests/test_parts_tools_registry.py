"""Реестр запчастей и инструмента (`data/parts_tools.json`, ночь 27→28.11): каждая запись — со страницы руководства
своего двигателя (дословный отрывок не длиннее 20 слов), поиск по узлу или операции, ответ «какой инструмент /
какие запчасти» — строками кода из реестра со ссылками, а не словами модели."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from service import parts_tools
from service.clients import MLClient, ToirClient
from service.fault_matrix import normalize
from service.manuals.catalog import documents_for_engine
from test_agent import make_agent, say

DATA = json.loads(parts_tools.PATH.read_text(encoding="utf-8"))
INDEX = Path(os.environ.get("INDEX_DIR", ".index"))


def _all() -> list[tuple[str, str, dict]]:
    return [(e, k, r) for e, d in DATA["engines"].items() for k in ("parts", "tools") for r in d[k]]


def test_records_are_short_quotes_from_own_engine_manuals() -> None:
    rows = _all()
    assert len(rows) > 500
    for engine, kind, r in rows:
        assert r["doc"] in {d.doc_id for d in documents_for_engine(engine)}, (engine, r)
        assert len(r["quote"].split()) <= 20, r  # не выгрузка страницы (#96)
        if kind == "parts" and r["designation"]:
            assert r["designation"] in r["quote"], r  # обозначение — дословно со строки перечня (D-29)


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_every_record_is_on_its_page() -> None:
    from service.manual_search import default_searcher

    page_text = default_searcher().page_text
    for engine, _, r in _all():
        text = page_text(r["doc"], r["page"]) or ""
        assert normalize(r["quote"]) in normalize(text), (engine, r["doc"], r["page"], r["quote"])


def test_find_by_operation_and_synonym() -> None:
    phases = parts_tools.find("ЗМЗ-40904.10", "Мне фазы проверить — чем мерить, приспособа какая?", {"tool"})
    assert ("24-Ф-74784.001", 135) in {(r.code, r.page) for r in phases}  # сектор из комплекта оснастки
    gap = parts_tools.find("ЯМЗ-236М2", "Чем проверить зазор в клапанах?", {"tool"})
    assert any(r.name == "щуп" for r in gap)
    pulley = parts_tools.find("ЗМЗ-5234.10", "Чем снять шкив коленчатого вала?", {"tool"})
    assert pulley[0].code == "16-У-236817"
    injector = parts_tools.find("ЯМЗ-536", "Снимаю форсунку — что заменить на новое?", {"part"}, limit=8)
    assert any(r.source == "одноразовая" and "инжектор" in r.name for r in injector)  # форсунка = инжектор


def test_other_engine_records_never_returned() -> None:
    zmz = {(r.doc) for r in parts_tools.find("ЗМЗ-40904.10", "щуп зазор клапан ключ съёмник", None, limit=50)}
    assert zmz and all(d.startswith("zmz-409") for d in zmz)


def test_asks() -> None:
    assert parts_tools.asks("Какой нужен инструмент") == {"tool"}
    assert parts_tools.asks("Какие нужны запчасти") == {"part"}
    assert parts_tools.asks("Что заменить на новое при сборке?") == {"part"}
    assert not parts_tools.asks("Какой зазор клапанов?")


def test_tool_question_answer_lines_from_registry(ml: MLClient, toir: ToirClient) -> None:
    """Модель назвала инструмент сама — строку «Понадобится» заменяет код: записи реестра со ссылками."""
    answer = "Фазы проверяют по меткам [R1].\n\nПонадобится: линейка и отвёртка.\n\n1. Снять крышку."
    ag, _ = make_agent([say(answer)] * 2, ml, toir, prefetch=False)
    reply = ag.ask(ag.start("Y815BM178", "S-0152"), "Чем проверить фазы газораспределения, какая оснастка?")
    assert "**Понадобится (по руководству):**" in reply.text and "24-Ф-74784.001 [R" in reply.text
    assert "линейка и отвёртка" not in reply.text
    assert any(s["pdf_page"] == 135 for s in reply.sources)


def test_non_tool_question_untouched(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Зазор 0,25-0,30 мм [R1].")] * 2, ml, toir, prefetch=False)
    reply = ag.ask(ag.start("B418HK98", "S-0007"), "Какой зазор клапанов?")
    assert "по руководству):**" not in reply.text
