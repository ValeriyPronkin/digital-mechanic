"""Число из соседней строки таблицы (независимый прогон 26.11): число ответа должно стоять в строке, где названа
деталь из вопроса или ответа. Таблица — Приложение В РК ЯМЗ-236 (стр. 286), текст как в индексе."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from service.clients import MLClient, ToirClient
from service.manual_search import ManualHit
from service.row_check import row_ok
from test_agent import make_agent, say

# Строки таблицы моментов переставлены: тесту порядок не важен, а длинного отрывка руководства подряд в
# открытом репозитории нет — не больше 24 слов (#96). Подпункты стоят под своим заголовком.
P286 = (
    "286\n"
    "Приложение B - Моменты затяжки основных резьбовых соединений\n"
    "Резьбовое соединение\n"
    "Момент затяжки\n"
    "Н·м (кгс·м)\n"
    "Гайки скоб крепления форсунок 50-62 (5-6,2)\n"
    "Болты крепления маховика 200-220 (20-22)\n"
    "Гайки крепления стоек осей коромысел 120-150 (12-15)\n"
    "Болты крепления крышек шатунов 200-220 (20-22)\n"
    "Гайки шпилек крепления\n"
    "головки цилиндров 240-260 (24-26)\n"
    "Болты крепления крышек коренных\n"
    "подшипников:\n"
    "\uf02d вертикальные 430-470 (43-47)\n"
    "\uf02d горизонтальные 100-120 (10-12)"
)
Q = "Какой момент затяжки гаек стоек осей коромысел?"


def test_number_of_other_row_rejected() -> None:
    assert not row_ok("Затянуть гайки стоек коромысел моментом 240-260 Н·м [R1].", Q, [P286])  # строка ГБЦ
    assert row_ok("Затянуть гайки стоек коромысел моментом 120-150 Н·м [R1].", Q, [P286])


def test_part_named_only_in_question_is_enough() -> None:
    assert row_ok("Момент — 120-150 Н·м [R1].", Q, [P286])
    assert not row_ok("Момент — 50-62 Н·м [R1].", Q, [P286])  # строка скоб форсунок


def test_sub_item_row_takes_heading() -> None:
    q = "Момент затяжки вертикальных болтов крышек коренных подшипников?"
    assert row_ok("Вертикальные — 430-470 Н·м [R1].", q, [P286])
    assert not row_ok("Болты крышек шатунов — 430-470 Н·м [R1].", "Момент болтов крышек шатунов?", [P286])


def test_number_in_prose_not_checked() -> None:
    page = "Давление масла на прогретом двигателе должно быть 400-700 кПа при 2100 об/мин и не менее 100 кПа."
    assert row_ok("Давление 400-700 кПа [R1].", "Какое давление масла?", [page])


class Table:
    available = True

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        return [ManualHit("yamz-236-rk", "РК", 286, "Приложение В", P286)]

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        return P286 if (manual_id, pdf_page) == ("yamz-236-rk", 286) else None


def test_agent_drops_sentence_with_number_from_other_row(ml: MLClient, toir: ToirClient) -> None:
    answer = "Гайки стоек осей коромысел: 240-260 Н·м [R1].\nГайки стоек осей коромысел: 120-150 Н·м [R1]."
    ag, _ = make_agent([say(answer)], ml, toir, Table())
    reply = ag.ask(ag.start("B418HK98", "S-0007"), Q)
    assert "240-260" not in reply.text and "120-150" in reply.text
    assert any("другую деталь" in n for n in reply.notes)


INDEX = Path(os.environ.get("INDEX_DIR", ".index"))


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_real_torque_table_rows() -> None:
    from service.manual_search import default_searcher

    page = default_searcher().page_text("yamz-236-rk", 286)
    assert page and not row_ok("Гайки стоек коромысел — 240-260 Н·м.", Q, [page])
    assert row_ok("Гайки стоек коромысел — 120-150 Н·м.", Q, [page])
