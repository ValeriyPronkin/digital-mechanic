"""Противоречивые инструкции (требование заказчика, 26.11): обе формулировки дословно со страницами, отметка
противоречия, совет уточнить у специалиста; известный кейс ЯМЗ-236 — вывод «регулировать на холодном»."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from service.clients import MLClient, ToirClient
from service.contradictions import ADVICE, HEADER, check_model_blocks, known, verified_quotes
from service.manual_search import ManualHit
from test_agent import make_agent, say

RE31 = "Тепловые зазоры регулировать на холодном двигателе или менее чем через 15 минут после его остановки."
RK269 = ("Проверить и подрегулировать тепловые зазоры клапанного механизма перед началом и по окончании обкатки, "
         "но не ранее, чем через 15 мин после остановки двигателя.")  # fmt: skip
RK276 = ("Проверку регулировки зазоров в клапанном механизме производить на холодном двигателе или не ранее, "
         "чем через 15 минут после его остановки.")  # fmt: skip
PAGES = {
    ("yamz-236-re", 31): "Регулировка клапанного механизма.\nВеличина зазора 0,25-0,30 мм.\n" + RE31,
    ("yamz-236-rk", 269): "6.4 Регулировка двигателя\n6.4.1 " + RK269,
    ("yamz-236-rk", 276): "Примечание - " + RK276,
}
QUESTION = "Когда регулировать зазоры клапанов на ЯМЗ-236 — сразу после остановки можно?"


class Manual236:
    available = True

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        return [ManualHit("yamz-236-re", "ЯМЗ-236М2 РЭ", 31, "Регулировка", PAGES[("yamz-236-re", 31)])]

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        return PAGES.get((manual_id, pdf_page))


def _ask(ml: MLClient, toir: ToirClient, answer: str, question: str = QUESTION, search: Any = None) -> Any:
    ag, llm = make_agent([say(answer)], ml, toir, search or Manual236())
    return ag.ask(ag.start("B418HK98", "S-0007"), question), llm


def test_known_case_shows_all_quotes_marks_and_concludes_cold(ml: MLClient, toir: ToirClient) -> None:
    reply, _ = _ask(ml, toir, "Можно в течение 15 минут после остановки [R1].")
    text = reply.text
    assert HEADER in text and ADVICE in text
    for quote in (RE31, RK269, RK276):
        assert quote in text  # каждая формулировка — дословно
    assert "стр. 31" in text and "стр. 269" in text and "стр. 276" in text
    assert "Регулировать зазоры на холодном двигателе" in text  # вывод заказчика
    assert {(s["pdf_page"]) for s in reply.sources} >= {31, 269, 276}  # ссылки на все страницы
    assert any("Противоречие" in n for n in reply.notes)


def test_model_sees_contradiction_in_search_result(ml: MLClient, toir: ToirClient) -> None:
    _, llm = _ask(ml, toir, "ок")
    tool = next(m for m in llm.seen[0] if m["role"] == "tool" and m.get("name") == "search_manual")
    c = json.loads(str(tool["content"]))["contradiction"]
    assert len(c["quotes"]) == 3 and "холодном" in c["conclusion"]


def test_value_question_is_not_timing_question(ml: MLClient, toir: ToirClient) -> None:
    reply, _ = _ask(ml, toir, "Зазор 0,25-0,30 мм [R1].", question="Какой тепловой зазор клапанов?")
    assert HEADER not in reply.text  # «тепловой» — не «на тёплом двигателе»


def test_answer_that_picks_one_timing_gets_block(ml: MLClient, toir: ToirClient) -> None:
    answer = ("Зазор 0,25-0,30 мм [R1].\n\n1. Регулировать зазоры на холодном двигателе или не позже 15 мин "
              "после остановки [R1].\n2. Снять крышки.\n\nПротиворечий в документации нет.")  # fmt: skip
    reply, _ = _ask(ml, toir, answer, question="Какой тепловой зазор клапанов?")
    text = reply.text
    assert HEADER in text and RK276 in text and "стр. 269" in text
    assert "не позже 15 мин" not in text and "Противоречий в документации нет" not in text
    assert "1. Регулировать на холодном двигателе" in text and "2. Снять крышки." in text


def test_timing_claim_without_digits_replaced(ml: MLClient, toir: ToirClient) -> None:
    answer = "Нет: на холодном или сразу после остановки, пока он не остыл.\n\n1. Снять крышки [R1]."
    reply, _ = _ask(ml, toir, answer, question="Можно регулировать клапаны на тёплом двигателе?")
    assert "пока он не остыл" not in reply.text and reply.text.startswith("Регулировать на холодном двигателе")


def test_safe_line_once_outside_list(ml: MLClient, toir: ToirClient) -> None:
    answer = "Не сразу после остановки.\n\n1. Снять крышки [R1].\n\nДо 15 мин после остановки не начинать."
    reply, _ = _ask(ml, toir, answer)
    assert reply.text.count("формулировки руководств о 15 минутах расходятся") == 1


def test_model_own_conclusion_dropped_one_conclusion_left(ml: MLClient, toir: ToirClient) -> None:
    reply, _ = _ask(ml, toir, "Нет, дайте остыть.\n\nВывод: можно через 15 минут.\n\n1. Снять крышки [R1].")
    assert reply.text.count("Вывод:") == 1 and "можно через 15 минут" not in reply.text
    assert "\n\n\n" not in reply.text


def test_unrelated_question_has_no_block(ml: MLClient, toir: ToirClient) -> None:
    reply, _ = _ask(ml, toir, "Зазор 0,25-0,30 мм [R1].", question="Какой момент затяжки гаек головки?")
    assert HEADER not in reply.text


def test_without_page_text_no_contradiction_claimed(ml: MLClient, toir: ToirClient) -> None:
    class NoPages:
        available = True

        def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
            return []

    reply, _ = _ask(ml, toir, "В руководстве не нашёл.", search=NoPages())
    assert HEADER not in reply.text  # цитаты не сверить — противоречие не заявляем


def test_model_block_kept_only_with_two_verified_quotes() -> None:
    sources = {"R1": PAGES[("yamz-236-re", 31)], "R2": PAGES[("yamz-236-rk", 269)]}
    good = f"Ответ.\n\nПротиворечие в документации:\n- «{RE31}» [R1]\n- «{RK269}» [R2]"
    text, notes = check_model_blocks(good, sources.get)
    assert RE31 in text and RK269 in text and ADVICE in text and not notes
    fake = f"Ответ.\n\nПротиворечие в документации:\n- «{RE31}» [R1]\n- «Регулировать на горячем двигателе сразу.» [R2]"
    text, notes = check_model_blocks(fake, sources.get)
    assert "Противоречие" not in text and "горячем" not in text and notes  # вторая цитата не со страницы — убрано


INDEX = Path(os.environ.get("INDEX_DIR", ".index"))


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_known_quotes_are_on_their_pages_in_real_index() -> None:
    from service.manual_search import default_searcher

    searcher = default_searcher()
    for k in known():
        assert len(verified_quotes(k, getattr(searcher, "page_text", None))) == len(k.quotes), k.id


def test_value_in_same_line_as_timing_claim_survives(ml: MLClient, toir: ToirClient) -> None:
    """Eval Q02: «Зазор 0,25–0,30 мм [R1]. Регулировать на холодном или через 15 мин» — значение остаётся."""
    answer = "Зазор 0,25-0,30 мм [R1]. Ставить на холодном или не позже 15 мин после остановки.\n\n1. Снять крышки."
    reply, _ = _ask(ml, toir, answer, question="Какой зазор на клапанах? На холодную или на горячую?")
    first = reply.text.split("\n\n")[0]
    assert "0,25-0,30 мм" in first and "не позже 15 мин" not in reply.text and "Регулировать на холодном" in first


# ---------- общий механизм: разные значения одного параметра (моменты затяжки) ----------

TORQUE_PAGES = {
    ("yamz-236-rk", 41): "затяжку болтов крепления крышек производить с моментом 421-461 Н*м (43-47 кгс*м)",
    ("yamz-236-rk", 56): "должны быть затянуты моментом силы от 421 до 461 Н·м ( от 43 до 47 кгс·м)",
    ("yamz-236-rk", 248): "- затянуть болты крепления крышек коренных подшипников не менее,\n"
    "чем в три приема, моментом силы от 421 до 461 Нм (от 42 до 46 кгс·м);",
    ("yamz-236-rk", 286): "Болты крепления крышек коренных\nподшипников:\n вертикальные 430-470 (43-47)",
    ("yamz-536-re", 274): "Болты крепления скоб форсунок в\nголовке цилиндров\nПредварительный момент\nзатяжки: 16±1 "
    "(1,6± 0,1)\nБолты крепления рампы 45 ± 2 (4,5 ± 0,2)",
    ("yamz-536-rk", 585): "Болты крепления скоб\nфорсунок в головке\nцилиндров\nПредварительный момент затяжки: 3-5 "
    "(SВН=6)\nОкончательный момент затяжки: 15-17 (SВН=6)\nБолты крепления\nрампы 22-25 (S=13)",
}


class TorquePages(Manual236):
    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        doc, page = ("yamz-536-rk", 585) if "536" in engine else ("yamz-236-rk", 286)
        return [ManualHit(doc, "РК", page, "Моменты затяжки", TORQUE_PAGES[(doc, page)])]

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        return TORQUE_PAGES.get((manual_id, pdf_page))


def test_main_bearing_torque_both_values_no_pick(ml: MLClient, toir: ToirClient) -> None:
    """ЯМЗ-236: 421–461 Н·м (РК стр. 41, 56, 248) против 430–470 Н·м (РК стр. 286) — оба, без выбора."""
    ag, _ = make_agent([say("Затянуть 430-470 Н·м [R1].\n\n1. В три приёма.")], ml, toir, TorquePages())
    question = "С каким моментом тянуть болты крышек коренных подшипников?"
    text = ag.ask(ag.start("B418HK98", "S-0007"), question).text
    assert HEADER in text and ADVICE in text and "Вывод:" not in text  # правила заказчика нет — не выбираем
    assert "421-461" in text and "430-470 (43-47)" in text
    for page in (41, 56, 248, 286):
        assert f"стр. {page}" in text
    assert "Затянуть 430-470 Н·м" not in text  # строка модели, выбравшая одно значение, заменена


def test_injector_bracket_torque_536(ml: MLClient, toir: ToirClient) -> None:
    """ЯМЗ-536: болты скоб форсунок — РЭ стр. 274 (16±1) против РК стр. 585 (3-5, затем 15-17)."""
    ag, _ = make_agent([say("Окончательно 15-17 [R1], затем 95°.")], ml, toir, TorquePages())
    text = ag.ask(ag.start("M260EH47", "S-0079"), "Какой момент затяжки болтов скоб форсунок?").text
    assert HEADER in text and "16±1" in text and "15-17 (SВН=6)" in text
    assert "стр. 274" in text and "стр. 585" in text and "Окончательно 15-17 [R1]" not in text


def test_safe_line_once_for_bullets(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("- Предварительно 3-5 [R2].\n- Окончательно 15-17 [R2].\n\n1. Довернуть на 95°.")],
                       ml, toir, TorquePages())  # fmt: skip
    text = ag.ask(ag.start("M260EH47", "S-0079"), "Какой момент затяжки болтов скоб форсунок?").text
    assert text.count("указан по-разному") == 1 and not text.startswith("\n")
