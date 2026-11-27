"""«Можно ли ехать» — сначала «да/нет», черновик заявки — только по просьбе механика (приёмщик 27.11, Q37: на
«Цепь стучит в передней части. Можно пока ездить?» ответ был целиком черновиком заявки, без «не эксплуатировать»)."""

from __future__ import annotations

import pytest

from service.agent import _DRIVE_ASK, TICKET_NOT_ASKED
from service.clients import MLClient, ToirClient
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
    assert first.startswith("**Ездить нельзя:**") and "не эксплуатировать" in first  # вердикт — кодом, первым


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
