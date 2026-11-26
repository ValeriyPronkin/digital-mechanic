"""Детерминированный поиск (штурман 26.11): глоссарий вместо плана от модели, язык — кодом, шапки страниц не в BM25,
пересортировка по лучшему отрезку 1–3 строки, эмбеддинги — настройкой SEARCH_SEMANTIC."""

from __future__ import annotations

import pytest

from service import glossary
from service.clients import MLClient, ToirClient
from service.manuals.index import Fragment
from service.manuals.lexical import BM25
from service.manuals.search import ManualIndex, coverage, header_lines, semantic_enabled
from test_agent import make_agent, say


def frag(doc: str, page: int, text: str, i: int = 0) -> Fragment:
    return Fragment(id=f"{doc}:{page}:{i}", doc_id=doc, designation="РК", engines=["ЗМЗ-5234.10"], kind="ремонт",
                    page=page, section="", source="текст", text=text, tokens=[])  # fmt: skip


def test_glossary_expands_shop_words() -> None:
    terms = glossary.expand("Гидрики стучат на холодную, помпа подтекает")
    assert "гидротолкатель толкатель" in terms and "водяной насос" in terms
    assert glossary.expand("Какой зазор клапанов?") == []


@pytest.mark.parametrize(
    ("text", "need"),
    [("Какой зазор клапанов?", False), ("Klapan zazori qanday?", True), ("Фишори равған чӣ қадар аст?", True),
     ("Двигатель ЯМЗ-236 TDI", False)],
)  # fmt: skip
def test_language_by_code(text: str, need: bool) -> None:
    assert glossary.needs_translation(text) is need


def test_russian_question_has_no_plan_call(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_MODE", "deterministic")
    ag, llm = make_agent([say("ответ")], ml, toir, plan_search=True)
    ag.ask(ag.start("B418HK98", "S-0007"), "Какой зазор клапанов?")
    assert len(llm.seen) == 1  # только ответ: плана от модели нет


def test_bm25_weights_halve_glossary_terms() -> None:
    bm = BM25([["насос", "водяной"], ["помпа"]])
    full = bm.scores(["насос"], [0, 1])[0]
    half = bm.scores(["насос"], [0, 1], {"насос": 0.5})[0]
    assert half == pytest.approx(full / 2)


def test_repeated_header_lines_not_indexed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_MODE", "deterministic")
    words = ["клапан", "поршень", "шатун", "вкладыш", "насос", "фильтр", "ремень", "цепь", "свеча", "карбюратор",
             "стартер", "генератор", "термостат", "радиатор", "маховик", "сцепление", "прокладка", "форсунка",
             "датчик", "коромысло"]  # fmt: skip
    frags = [frag("zmz-5234-rk", p, f"Руководство по ремонту двигателя ЗМЗ\nПроверить {words[p - 1]}")
             for p in range(1, 21)]  # fmt: skip
    frags.append(frag("zmz-5234-rk", 21, "Насос масляный: проверить давление"))
    hdr = header_lines(frags)["zmz-5234-rk"]
    assert "руководство по ремонту двигателя змз" in hdr
    idx = ManualIndex(frags)
    assert "руководство" not in idx.bm25.tf[0]  # шапка не в BM25
    assert idx.bm25.tf[0]  # остальной текст — в BM25


def test_coverage_best_segment_of_up_to_three_lines() -> None:
    q = {"зазор", "клапан", "мм"}
    assert coverage("зазор\nклапанов\n0,25 мм\nдругое", q) == 1.0
    assert coverage("зазор\nа\nб\nв\nклапан", q) == pytest.approx(1 / 3)


def test_semantic_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_SEMANTIC", "0")
    assert semantic_enabled() is False
    monkeypatch.setenv("SEARCH_SEMANTIC", "1")
    assert semantic_enabled() is True


def test_default_mode_is_main_behaviour(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """По умолчанию — как в main: план от модели на русский вопрос, шапки в BM25, без глоссария."""
    monkeypatch.delenv("SEARCH_MODE", raising=False)
    ag, llm = make_agent([say('{"lang":"ru","question_ru":"q","queries":["q"]}'), say("ответ")], ml, toir,
                         plan_search=True)  # fmt: skip
    ag.ask(ag.start("B418HK98", "S-0007"), "Какой зазор клапанов?")
    assert len(llm.seen) == 2  # план + ответ
    idx = ManualIndex([frag("zmz-5234-rk", p, f"Шапка руководства ЗМЗ\nстр {p}") for p in range(1, 21)])
    assert not idx.deterministic and not idx.headers
