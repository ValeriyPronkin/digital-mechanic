"""«Можно ли ехать» — сначала «да/нет», черновик заявки — только по просьбе механика (приёмщик 27.11, Q37: на
«Цепь стучит в передней части. Можно пока ездить?» ответ был целиком черновиком заявки, без «не эксплуатировать»)."""

from __future__ import annotations

import pytest

from service.agent import _DRIVE_ASK, TICKET_NOT_ASKED
from service.clients import MLClient, ToirClient
from service.manual_search import ManualHit
from test_agent import DRAFT, call, make_agent, say

Q37 = ("Y815BM178", "S-0153")  # F14 цепь ГРМ, срочность высокая
QUESTION = "Цепь стучит в передней части. Можно пока ездить?"


@pytest.mark.parametrize(
    "q",
    [QUESTION, "Можно ли ехать?", "Можно ещё ездить на ней?", "Доеду до базы?", "Перегнать своим ходом можно?",
     "Можно эксплуатировать до ТО?", "Не опасно ехать дальше?"],
)  # fmt: skip
def test_drive_questions_recognised(q: str) -> None:
    assert _DRIVE_ASK.search(q)


def test_no_draft_on_drive_question(ml: MLClient, toir: ToirClient) -> None:
    steps = [call("draft_ticket", **DRAFT), say("Черновик готов, отправьте кнопкой «Отправить».")]
    ag, llm = make_agent(steps, ml, toir)
    reply = ag.ask(ag.start(*Q37), QUESTION)
    assert reply.draft is None
    refused = [m for m in llm.seen[-1] if m["role"] == "tool" and m.get("name") == "draft_ticket"]
    assert refused and TICKET_NOT_ASKED in str(refused[0]["content"])
    first = reply.text.split("\n\n")[0]
    # вердикт кода — первым, но рекомендация, а не запрет: запрет — только словами руководства с его страницей
    assert first.startswith("**Прямого запрета эксплуатации") and "дефектовка до выпуска в рейс" in first
    assert "нельзя" not in first and "не эксплуатировать" not in first


def test_model_verdict_kept(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("**Ездить нельзя:** до устранения стуков двигатель не эксплуатировать [R1].")], ml, toir)
    reply = ag.ask(ag.start(*Q37), QUESTION)
    assert reply.text.startswith("**Ездить нельзя:** до устранения") and reply.text.count("Ездить нельзя") == 1


def test_yes_after_offer_builds_draft(ml: MLClient, toir: ToirClient) -> None:
    steps = [say("Ездить нельзя [R1]. Оформить заявку на дефектовку?"), call("draft_ticket", **DRAFT),
             say("Черновик готов [R1].")]  # fmt: skip
    ag, _ = make_agent(steps, ml, toir)
    conv = ag.start(*Q37)
    ag.ask(conv, QUESTION)
    assert ag.ask(conv, "Да").draft is not None  # согласие на предложенную заявку — просьба


def test_explicit_request_builds_draft(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([call("draft_ticket", **DRAFT), say("Черновик готов [R1].")], ml, toir)
    assert ag.ask(ag.start(*Q37), "Оформи заявку на дефектовку").draft is not None


class LimitPages:
    available = True

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        return []

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        if (manual_id, pdf_page) == ("zmz-409-rk", 91):
            return "При появлении в работающем двигателе стуков двигатель не эксплуатировать."
        return None


def test_card_only_verdict_gets_manual_page(ml: MLClient, toir: ToirClient) -> None:
    """«Нельзя» только по карточке, без ссылки — код добавляет страницу ограничений эксплуатации (Q37: стр. 91)."""
    ag, _ = make_agent([say("**Нет, ездить нельзя.** По карточке срочность высокая.")], ml, toir, LimitPages(),
                       prefetch=False)  # fmt: skip
    reply = ag.ask(ag.start(*Q37), QUESTION)
    first = reply.text.split("\n\n")[0]
    assert first.startswith("**Нет, ездить нельзя.** [R")  # запрет модели — со страницей руководства
    assert "По руководству, стр. 91 [R" in first and "не эксплуатировать" in first  # словами руководства
    assert "Прямого запрета" not in reply.text
    assert (reply.sources[-1]["pdf_page"], reply.sources[-1]["manual"].startswith("ЗМЗ")) == (91, True)


def test_no_verdict_gets_manual_words_not_no_ban_line(ml: MLClient, toir: ToirClient) -> None:
    """Train 27.11: код писал «Прямого запрета эксплуатации… нет» и тут же ссылался на стр. 91, где «двигатель не
    эксплуатировать». Есть фраза-запрет по теме вопроса на странице ограничений — первой строкой она, со страницей."""
    ag, _ = make_agent([say("Цепь может быть вытянута.\n\n1. Прослушать натяжитель.")], ml, toir, LimitPages(),
                       prefetch=False)  # fmt: skip
    reply = ag.ask(ag.start(*Q37), QUESTION)
    first = reply.text.split("\n\n")[0]
    assert first.startswith("**По руководству, стр. 91 [R") and "не эксплуатировать" in first
    assert "Прямого запрета" not in reply.text
