"""Узла у двигателя нет (скрытая половина 27.11, регрессия поезда против main): первой строкой — «У <двигателя> нет
<узла>» и факт конструкции со страницей, затем действие. И на вопрос о карточке с несовместимым кодом, и на вопрос
о детали другого двигателя парка («цепь» у ЯМЗ — шестерни)."""

from __future__ import annotations

from typing import Any

import pytest

from service import absent_parts
from service.clients import MLClient, ToirClient
from service.manual_search import ManualHit
from test_agent import make_agent, say


class Pages:
    """Страница-основание каждой записи «узла нет» — с её цитатой (цитаты сверяет `absent_parts.verified`)."""

    available = True

    def __init__(self) -> None:
        self.pages: dict[tuple[str, int], str] = {}
        for a in absent_parts.items():
            for q in a.quotes:
                self.pages[(q.doc, q.page)] = f"{self.pages.get((q.doc, q.page), '')}\n{q.quote}"

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        return []

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        return self.pages.get((manual_id, pdf_page))


def _ask(ml: MLClient, toir: ToirClient, vehicle: str, session: str, question: str, answer: str) -> Any:
    ag, _ = make_agent([say(answer)] * 3, ml, toir, Pages(), prefetch=False)
    return ag.ask(ag.start(vehicle, session), question)


@pytest.mark.parametrize(
    ("vehicle", "session", "head"),
    [
        ("P854BT78", "S-0021", "**У ЯМЗ-236М2 нет цепи ГРМ и гидронатяжителя.**"),  # F14 на шестернях
        ("C808CM178", "S-0144", "**У ЗМЗ-5234.10 нет турбокомпрессора.**"),  # F09 на карбюраторном
    ],
)
def test_incompatible_card_answer_starts_with_absent_part(
    ml: MLClient, toir: ToirClient, vehicle: str, session: str, head: str
) -> None:
    reply = _ask(ml, toir, vehicle, session, "Что с двигателем?", "Нужна дефектовка узла.")
    first = reply.text.split("\n\n")[0]
    assert first.startswith(head) and "стр. " in first and "[R" in first  # факт конструкции со страницей
    assert "дефектовк" in reply.text  # затем действие


def test_part_of_another_engine_plain_word(ml: MLClient, toir: ToirClient) -> None:
    """«Цепь» у ЯМЗ-236М2 (у ЗМЗ-409 она есть) — ответ кода «нет», а не «нужна дефектовка»."""
    reply = _ask(ml, toir, "B418HK98", "S-0007", "Цепь стучит, что проверить?", "Нужна дефектовка узла.")
    assert reply.text.startswith("**У ЯМЗ-236М2 нет цепи ГРМ и гидронатяжителя.**")


def test_compatible_card_gets_no_absent_line(ml: MLClient, toir: ToirClient) -> None:
    reply = _ask(ml, toir, "B418HK98", "S-0007", "Что с двигателем?", "Зазоры клапанов нарушены.")
    assert " нет " not in reply.text.split("\n")[0]
