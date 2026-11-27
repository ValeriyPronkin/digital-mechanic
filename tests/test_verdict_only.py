"""Кнопка «Получить результат диагностики» при норме и сбое записи — строка кода, без модели (приёмка 27.11).

C808CM178 / S-0145 (норма): после «двигатель в норме» модель давала порядок ТО — крепление стартера, «через 96…»,
страницы 71 и 135. H142OX78 / S-0113 (сбой записи): модель пересказывала карточку слово в слово. Карточка проверки и
есть ответ; вопрос механика после неё идёт модели, как обычно.
"""

from __future__ import annotations

import re

import pytest

from service.agent import Agent
from service.clients import MLClient, ToirClient
from test_agent import FAILED, FixtureSearch, make_agent, say

BUTTON = "Получить результат диагностики"
NORMAL = ("C808CM178", "S-0145")
VERDICT_ON_ENGINE = re.compile(r"двигатель\s+(?:в\s+норме|исправен)", re.I)


def _button(ml: MLClient, toir: ToirClient, pair: tuple[str, str]) -> tuple[Agent, object, FixtureSearch, object]:
    search = FixtureSearch()
    ag, llm = make_agent([], ml, toir, search)  # любой вызов модели — IndexError: сценарий пуст
    conv = ag.start(*pair)
    return ag, llm, search, (conv, ag.ask(conv, BUTTON))


@pytest.mark.parametrize("pair", [NORMAL, FAILED], ids=["normal", "check_failed"])
def test_button_on_normal_or_failed_check_is_one_code_line(
    ml: MLClient, toir: ToirClient, pair: tuple[str, str]
) -> None:
    _, llm, search, (_, reply) = _button(ml, toir, pair)
    assert llm.seen == []  # type: ignore[attr-defined]
    assert search.engines == []  # ни поиска, ни страниц руководства
    assert reply.sources == [] and reply.draft is None and reply.trace["cost_rub"] == 0
    assert "\n" not in reply.text.strip() and len(reply.text) < 200
    assert not VERDICT_ON_ENGINE.search(reply.text)
    assert not re.search(r"\b(?:я|мы|нашёл|делаю|оформляем)\b", reply.text, re.I)  # без первого лица


def test_normal_says_no_deviations_and_no_ticket(ml: MLClient, toir: ToirClient) -> None:
    _, _, _, (_, reply) = _button(ml, toir, NORMAL)
    assert reply.text.startswith("Отклонений не найдено")
    assert "только звук" in reply.text and "заявка не нужна" in reply.text


def test_failed_says_no_conclusion_and_no_ticket(ml: MLClient, toir: ToirClient) -> None:
    _, _, _, (_, reply) = _button(ml, toir, FAILED)
    assert "выводов о двигателе нет" in reply.text and "заявка не оформляется" in reply.text
    assert "Повторите запись" in reply.text


def test_diagnosis_is_in_history_and_followup_goes_to_model(ml: MLClient, toir: ToirClient) -> None:
    search = FixtureSearch()
    ag, llm = make_agent([say("Ответ по руководству.")], ml, toir, search)
    conv = ag.start(*NORMAL)
    first = ag.ask(conv, BUTTON)
    assert any(s.get("tool") == "get_diagnosis" for s in first.trace["steps"])  # карточка — в журнале действий
    ag.ask(conv, "Как проверить свечи зажигания?")
    assert len(llm.seen) == 1 and search.engines  # вопрос механика — модели, с поиском по руководству
    assert any(m.get("role") == "tool" and m.get("name") == "get_diagnosis" for m in llm.seen[0])


def test_ticket_refusal_on_normal_does_not_call_engine_normal() -> None:
    from service.clients import Diagnosis
    from service.verdict_policy import VerdictCard

    diag = Diagnosis.model_validate(
        {"vehicle_id": "X", "session_id": "S", "status": "normal", "anomaly_type": None, "anomaly_title": None,
         "anomaly_score": 0.1, "confidence": 0.9, "signal_quality": "good", "description": "", "model_version": "1"}
    )  # fmt: skip
    card = VerdictCard(
        status="normal",
        color="green",
        title="t",
        action="a",
        banners=[],
        ticket_possible=False,
        fault_code=None,
        fault_title=None,
        confidence_pct=90,
        ml_quote="",
        ml_quote_label="",
    )
    text = Agent._ticket_refusal(diag, card)
    assert text == "Отклонений не найдено — заявка не нужна."
