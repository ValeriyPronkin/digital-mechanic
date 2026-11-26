"""#40 п. 2 — норма и предел; п. 5 — фраза через границу страницы не снимается проверкой цифр."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from service.clients import MLClient, ToirClient
from service.manual_search import ManualHit
from service.norm_limits import HEADER, items, verified
from test_agent import make_agent, say

NORM = ("Давление масла на прогретом двигателе должно быть 400-700 кПа (4-7 кгс/см2 ) при 2100 об/мин и не менее "
        "100 кПа (1,0 кгс/см2 ) при минимальной частоте вращения холостого хода коленчатого вала")  # fmt: skip
LIMIT = ("После длительной эксплуатации допускается работа двигателя при давлении масла в системе смазки не ниже "
         "300 кПа (3,0 кгс/см2 ) на номинальной частоте вращения и не ниже 50 кПа (0,5 кгс/см2 ) на минимальной "
         "частоте вращения коленчатого вала")  # fmt: skip
PAGES = {
    ("yamz-236-re", 19): f"{NORM}. {LIMIT}.",
    ("yamz-236-rk", 142): "Затянуть гайки крепления головки моментом",
    ("yamz-236-rk", 143): "240-260 Н·м (24-26 кгс·м) в три приёма. Далее проверить зазоры.",
}


class Pages:
    available = True

    def __init__(self, page: tuple[str, int]) -> None:
        self.page = page

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        return [ManualHit(self.page[0], "РЭ", self.page[1], "", PAGES[self.page])]

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        return PAGES.get((manual_id, pdf_page))


def test_norm_and_limit_both_shown_with_labels(ml: MLClient, toir: ToirClient) -> None:
    answer = say("Давление 400-700 кПа [R1].\n\n1. Прогреть двигатель.")
    ag, _ = make_agent([answer], ml, toir, Pages(("yamz-236-re", 19)))
    text = ag.ask(ag.start("B418HK98", "S-0007"), "Какое должно быть давление масла?").text
    assert HEADER in text and "Норма (исправный прогретый двигатель)" in text and "Предел после длительной" in text
    assert NORM in text and LIMIT in text and "стр. 19" in text
    assert text.index(HEADER) < text.index("1. Прогреть")  # блок — сразу после прямого ответа


def test_other_question_no_norm_block(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Ответ [R1].")], ml, toir, Pages(("yamz-236-re", 19)))
    assert HEADER not in ag.ask(ag.start("B418HK98", "S-0007"), "Какой зазор клапанов?").text


def test_number_from_sentence_continued_on_next_page_kept(ml: MLClient, toir: ToirClient) -> None:
    """Фраза «…моментом» на стр. 142 → «240-260 Н·м» на стр. 143: цифры со ссылкой на стр. 142 не снимаются."""
    answer = say("Затянуть гайки головки моментом 240-260 Н·м [R1].")
    ag, _ = make_agent([answer], ml, toir, Pages(("yamz-236-rk", 142)))
    reply = ag.ask(ag.start("B418HK98", "S-0007"), "С каким моментом тянуть гайки головки?")
    assert "240-260 Н·м" in reply.text and not any("цифр" in n for n in reply.notes)


INDEX = Path(os.environ.get("INDEX_DIR", ".index"))


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_norm_limit_quotes_on_pages_in_real_index() -> None:
    from service.manual_search import default_searcher

    page_text = getattr(default_searcher(), "page_text", None)
    for n in items():
        assert verified(n, page_text), n.id
