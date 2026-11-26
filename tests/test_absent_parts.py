"""«Нет в руководстве» (приёмка v2, ТЗ F4): узла у двигателя нет — ответ кода с цитатами, без советов модели;
страницы стендовых испытаний помечаются; «мнение помощника» — только общий совет."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from service.absent_parts import NOT_APPLICABLE, items, verified
from service.agent import bench_context
from service.clients import MLClient, ToirClient
from service.manual_search import ManualHit
from test_agent import make_agent, say

PAGES = {
    ("zmz-409-rk", 43): "Кулачки распределительных валов действуют непосредственно на гидротолкатели 10. "
    "Применение гидравлических толкателей в приводе клапанов исключает необходимость регулировки зазоров.",
    ("yamz-236-re", 6): "Тип двигателя Четырехтактный, с воспламенением от сжатия",
    ("yamz-236-re", 7): "Распределительный вал Общий для обоих рядов цилиндров, с шестеренчатым приводом",
    ("yamz-236-re", 8): "Топливный насос высокого давления",
    ("yamz-236-re", 109): "Все двигатели производства ОАО «Автодизель» без турбонаддува с маркой «ЯМЗ» соответствуют "
    "требованиям экологических нормативов Евро - 0.",
    ("yamz-236-rk", 276): "Аварийная защита стенда срабатывает при давлении масла ниже 100 кПа.",
}


class Pages:
    available = True

    def __init__(self, hits: list[ManualHit] | None = None) -> None:
        self.hits = hits or []

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        return self.hits

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        return PAGES.get((manual_id, pdf_page))


def _ask(ml: MLClient, toir: ToirClient, vehicle: tuple[str, str], question: str, answer: str = "ответ модели",
         search: Any = None) -> tuple[Any, Any]:  # fmt: skip
    ag, llm = make_agent([say(answer)], ml, toir, search or Pages())
    return ag.ask(ag.start(*vehicle), question), llm


ZMZ409 = ("E622KM47", "S-0195")
YAMZ236 = ("O263CH47", "S-0028")


def test_rockers_on_zmz409_answered_by_code_without_model(ml: MLClient, toir: ToirClient) -> None:
    reply, llm = _ask(ml, toir, ZMZ409, "Какой момент затяжки гаек стоек оси коромысел?", "120–150 Н·м")
    assert reply.text.startswith("**У ЗМЗ-40904.10 нет коромысел")
    assert "исключает необходимость регулировки зазоров" in reply.text and "стр. 43" in reply.text
    assert NOT_APPLICABLE in reply.text and "120" not in reply.text  # чужих цифр нет
    assert not llm.seen and reply.trace["cost_rub"] == 0  # модель не вызывалась
    assert [s["pdf_page"] for s in reply.sources] == [43]


def test_turbo_on_atmospheric_yamz236(ml: MLClient, toir: ToirClient) -> None:
    reply, llm = _ask(ml, toir, YAMZ236, "Как проверить люфт ротора турбокомпрессора?")
    assert "нет турбокомпрессора" in reply.text and {s["pdf_page"] for s in reply.sources} == {6, 109}
    assert "люфт" not in reply.text.lower() and not llm.seen


def test_turbo_mention_on_spec_pages_blocks_code_answer(ml: MLClient, toir: ToirClient) -> None:
    PAGES[("yamz-236-re", 8)] = "Турбокомпрессор ТКР-7"  # характеристика упоминает узел — не утверждаем «нет»
    try:
        reply, llm = _ask(ml, toir, YAMZ236, "Как проверить люфт ротора турбокомпрессора?", "В руководстве не нашёл.")
    finally:
        PAGES[("yamz-236-re", 8)] = "Топливный насос высокого давления"
    assert "нет турбокомпрессора" not in reply.text and llm.seen


def test_existing_part_goes_to_model(ml: MLClient, toir: ToirClient) -> None:
    reply, llm = _ask(ml, toir, YAMZ236, "Какой момент затяжки гаек стоек оси коромысел?", "В руководстве не нашёл.")
    assert llm.seen and "нет коромысел" not in reply.text  # у ЯМЗ-236 коромысла есть


def test_without_page_text_model_answers(ml: MLClient, toir: ToirClient) -> None:
    class NoPages:
        available = True

        def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
            return []

    reply, llm = _ask(ml, toir, ZMZ409, "Как отрегулировать коромысла?", "В руководстве не нашёл.", NoPages())
    assert llm.seen and "нет коромысел" not in reply.text


def test_bench_page_marked_in_answer_and_sources(ml: MLClient, toir: ToirClient) -> None:
    hit = ManualHit("yamz-236-rk", "ЯМЗ-236 РК", 276, "6.5 Приёмо-сдаточные испытания", PAGES[("yamz-236-rk", 276)])
    reply, llm = _ask(ml, toir, ("B418HK98", "S-0007"), "При каком давлении масла глушить двигатель?",
                      "Защита срабатывает ниже 100 кПа [R1].", Pages([hit]))  # fmt: skip
    assert reply.text == "Защита срабатывает ниже 100 кПа [R1]. (испытания на стенде)"
    assert reply.sources[0]["context"] == "испытания на стенде"
    tool = next(m for m in llm.seen[0] if m["role"] == "tool" and m.get("name") == "search_manual")
    assert "испытания на стенде" in str(tool["content"])


def test_bench_ranges() -> None:
    assert bench_context("yamz-236-rk", 269) and bench_context("yamz-536-rk", 575)
    assert bench_context("yamz-236-re", 269) is None and bench_context("yamz-236-rk", 100) is None


INDEX = Path(os.environ.get("INDEX_DIR", ".index"))


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_absent_quotes_on_their_pages_in_real_index() -> None:
    from service.manual_search import default_searcher

    page_text = getattr(default_searcher(), "page_text", None)
    for a in items():
        assert verified(a, page_text), a.id
