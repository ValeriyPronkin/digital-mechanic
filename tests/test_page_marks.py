"""Подсветка строки цитаты на картинке страницы (приём Никиты page_marks): неверная отметка хуже никакой."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from service import api_v2, main
from service.clients import MLClient, ToirClient
from service.page_marks import PageMarks, find_mark
from service.pages import PageImages
from test_agent import make_agent
from test_pages_v2 import Bucket

LINES = [
    {"t": "6.5.4 Проверить угол опережения впрыска топлива и зазоры в клапанном", "b": [0.19, 0.09, 0.92, 0.10]},
    {"t": "необходимо, отрегулироватьихвпределах 0,25 - 0,30 мм.", "b": [0.12, 0.59, 0.69, 0.61]},
    {"t": "Момент затяжки 120 - 150 Н·м", "b": [0.12, 0.70, 0.50, 0.72]},
    {"t": "Момент затяжки 120 - 150 Н·м", "b": [0.12, 0.80, 0.50, 0.82]},
]


def test_whole_line_and_line_holding_the_quote() -> None:
    assert find_mark(LINES, "необходимо, отрегулировать их в пределах 0,25 – 0,30 мм.") == (0.12, 0.59, 0.69, 0.61)
    assert find_mark(LINES, "угол опережения впрыска топлива") == (0.19, 0.09, 0.92, 0.10)  # цитата внутри строки


def test_no_mark_when_not_unique_or_numbers_missing() -> None:
    assert find_mark(LINES, "Момент затяжки 120 - 150 Н·м") is None  # две одинаковые строки — не угадываем
    quote = "отрегулировать их в пределах 0,25 - 0,35 мм и проверить снова"  # 0,35 на странице нет
    assert find_mark(LINES, quote) is None
    assert find_mark(LINES, "мм") is None  # слишком коротко


def test_short_quote_with_number_marked_only_when_unique() -> None:
    """«15 мин» короче порога: рамка — если это ровно одна строка с тем же числом (стр. 269, 27.11)."""
    lines = [
        *LINES,
        {"t": "но не ранее, чем через 15 мин", "b": [0.12, 0.30, 0.60, 0.32]},
        {"t": "после остановки двигателя.", "b": [0.12, 0.33, 0.50, 0.35]},
    ]
    assert find_mark(lines, "15 мин") == (0.12, 0.30, 0.60, 0.32)
    assert find_mark(lines, "120 -") is None  # в двух одинаковых строках — не угадываем
    assert find_mark(lines, "20 мин") is None  # такого числа на странице нет
    assert find_mark(lines, "двиг") is None  # короткое без числа не обводим


class Marks(PageMarks):
    def lines(self, doc_id: str, page: int) -> list[dict[str, Any]]:
        return LINES if (doc_id, page) == ("yamz-236-rk", 270) else []


def test_page_view_has_mark_for_quote(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([], ml, toir)
    images = PageImages(Bucket())
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(
            lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore(), None, lambda: images, Marks
        )
    )
    c = TestClient(app)
    url = "/api/v2/vehicles/M333YK47/pages/yamz-236-rk/270"
    view = c.get(url, params={"quote": "необходимо, отрегулировать их в пределах 0,25 - 0,30 мм."}).json()
    assert view["marks"] == [{"x": 0.12, "y": 0.59, "w": 0.57, "h": 0.02}] and view["focus"] == view["marks"][0]
    assert c.get(url).json()["marks"] == []  # без цитаты — без отметки


RUN = [
    {"t": "Примечание - Проверку регулировки зазоров в клапанном механизме", "b": [0.19, 0.14, 0.88, 0.16]},
    {
        "t": "производить на холодном двигателе или не ранее, чем через 15 минут после его",
        "b": [0.12, 0.17, 0.92, 0.19],
    },
    {"t": "остановки.", "b": [0.12, 0.20, 0.23, 0.21]},
    {"t": "6.5.5 Попадание топлива в стакан форсунки", "b": [0.19, 0.22, 0.90, 0.24]},
]


def test_sentence_wrapped_over_lines_gets_one_frame_around_them() -> None:
    quote = (
        "Проверку регулировки зазоров в клапанном механизме производить на холодном двигателе "
        "или не ранее, чем через 15 минут после его остановки."
    )
    assert find_mark(RUN, quote) == (0.12, 0.14, 0.92, 0.21)
    assert find_mark(RUN + RUN, quote) is None  # тот же абзац дважды — не угадываем
    hyphen = [
        {"t": "- Проверить момент затяжки болтов креп\ufffe", "b": [0.1, 0.1, 0.9, 0.12]},
        {"t": "-", "b": [0.1, 0.13, 0.11, 0.135]},
        {"t": "ления осей коромысел, который должен быть 120 - 150 Н·м.", "b": [0.1, 0.14, 0.8, 0.16]},
    ]
    assert find_mark(
        hyphen, "- Проверить момент затяжки болтов крепления осей коромысел, который должен быть 120 - 150 Н·м."
    ) == (0.1, 0.1, 0.9, 0.16)


def test_real_page_lines_from_pdf() -> None:
    from service.manual_search import manual_pdf
    from service.page_marks import page_lines

    path = manual_pdf("yamz-236-rk")
    if path is None:
        pytest.skip("нужны PDF руководств (MANUALS_DIR)")
    lines = page_lines(path)[276]
    box = find_mark(lines, "производить на холодном двигателе или не ранее, чем через 15 минут после его")
    assert box is not None and 0 < box[0] < box[2] <= 1 and 0 < box[1] < box[3] <= 1
    assert not any(ln["t"] == "," for ln in lines)  # запятая — в своей строке, не отдельно
    quote = (
        "Проверку регулировки зазоров в клапанном механизме производить на холодном двигателе "
        "или не ранее, чем через 15 минут после его остановки."
    )
    assert find_mark(lines, quote) is not None  # предложение на трёх строках печати
