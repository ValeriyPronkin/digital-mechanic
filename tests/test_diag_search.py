"""Поиск к результату диагностики — по неисправности из карточки, а не по тексту кнопки.

Стенд 27.11: на «Получить результат диагностики» план поиска искал сам текст кнопки и общие фразы — у A427MA78 (F03)
и T792HO98 (F02) одни и те же четыре страницы (приёмка в ремонт, стенд после ремонта, таблица генератора).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from service import glossary
from service.clients import MLClient, ToirClient
from service.manual_search import IndexSearcher, ManualHit
from service.manuals.search import ManualIndex
from test_agent import make_agent, say

INDEX = Path(os.environ.get("INDEX_DIR", ".index"))
BUTTON = "Получить результат диагностики"
DEMO = (("A427MA78", "S-0032", "Перегрев, охлаждающая жидкость в масле", 54),
        ("T792HO98", "S-0043", "Низкое давление масла", 53))  # fmt: skip


class Recorder:
    available = True

    def __init__(self, inner: Any = None) -> None:
        self.inner = inner
        self.queries: list[str] = []
        self.hits: list[ManualHit] = []

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        self.queries.append(query)
        if self.inner is None:
            return [ManualHit("yamz-236-re", "РЭ", 54, "Неисправности", "Заменить прокладку головки цилиндров.")]
        hits = self.inner.search(query, engine, k=k)
        self.hits += hits
        return hits


@pytest.mark.parametrize(("vehicle", "session", "title", "_page"), DEMO)
def test_button_searches_by_fault_title_without_plan(
    ml: MLClient, toir: ToirClient, vehicle: str, session: str, title: str, _page: int
) -> None:
    rec = Recorder()
    ag, llm = make_agent([say("ответ")], ml, toir, rec, plan_search=True)
    ag.ask(ag.start(vehicle, session), BUTTON)
    assert len(llm.seen) == 1  # плана от модели нет: в тексте кнопки нечего переводить и искать
    assert rec.queries == [" ".join([title, *glossary.expand(title)])]
    assert all(BUTTON not in q for q in rec.queries)


def test_own_question_still_searched_by_its_words(ml: MLClient, toir: ToirClient) -> None:
    rec = Recorder()
    ag, _ = make_agent([say("ответ")], ml, toir, rec)
    ag.ask(ag.start("A427MA78", "S-0032"), "Какой момент затяжки гаек головки цилиндров?")
    assert rec.queries == ["Какой момент затяжки гаек головки цилиндров?"]


def test_normal_check_button_has_no_search_own_question_has(ml: MLClient, toir: ToirClient) -> None:
    rec = Recorder()
    ag, llm = make_agent([say("ответ")], ml, toir, rec)
    conv = ag.start("A427MA78", "S-0030")
    ag.ask(conv, BUTTON)  # норма: ответ — строка кода под карточкой, без поиска и модели (приёмка 27.11)
    assert rec.queries == [] and llm.seen == []
    ag.ask(conv, "Какой момент затяжки гаек головки цилиндров?")
    assert rec.queries == ["Какой момент затяжки гаек головки цилиндров?"]


def test_fault_titles_get_manual_terms() -> None:
    assert "пониженное давление масла в системе смазки" in glossary.expand("Низкое давление масла")
    f03 = glossary.expand("Перегрев, охлаждающая жидкость в масле")
    assert any("в систему смазки попадает вода" in t for t in f03)
    assert "рециркуляция отработавших газов" not in f03  # «пЕРЕГРев» — не EGR
    assert glossary.expand("клапан ЕГР") == ["рециркуляция отработавших газов"]


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
@pytest.mark.parametrize(("vehicle", "session", "_title", "page"), DEMO)
def test_demo_vehicles_first_page_is_troubleshooting_table(
    ml: MLClient, toir: ToirClient, vehicle: str, session: str, _title: str, page: int
) -> None:
    """На собранном индексе: первая страница — таблица неисправностей РЭ ЯМЗ-236М2 (F03 — стр. 54, F02 — стр. 53)."""
    rec = Recorder(IndexSearcher(ManualIndex.load(INDEX)))
    ag, _ = make_agent([say("ответ")], ml, toir, rec)
    ag.ask(ag.start(vehicle, session), BUTTON)
    assert (rec.hits[0].manual_id, rec.hits[0].pdf_page) == ("yamz-236-re", page)
