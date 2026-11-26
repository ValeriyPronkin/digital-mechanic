"""Вопрос про другой двигатель (независимый прогон 26.11, п. 2): модель в вопросе распознаёт код; не двигатель
машины — чистый отказ без цифр, без вызова модели."""

from __future__ import annotations

import re

import pytest

from service.clients import MLClient, ToirClient
from service.other_engine import other
from test_agent import make_agent, say


@pytest.mark.parametrize(
    ("question", "engine", "expected"),
    [
        ("А у ЯМЗ-7511 какой зазор клапанов?", "ЯМЗ-236М2", "ЯМЗ-7511"),
        ("у ЯМЗ-238 момент затяжки ГБЦ?", "ЯМЗ-236М2", "ЯМЗ-238"),
        ("А на ЗМЗ-5234 как регулировать?", "ЯМЗ-536", "ЗМЗ-5234"),
        ("КамАЗ-740 форсунки как проверить?", "ЯМЗ-536", "КамАЗ-740"),
        ("Зазор клапанов на ЯМЗ-236?", "ЯМЗ-236М2", None),  # свой двигатель без модификации
        ("ЗМЗ-409 гидрики стучат", "ЗМЗ-40904.10", None),  # своё семейство
        ("ЯМЗ-5361 рампа — момент?", "ЯМЗ-536", None),  # модификация того же руководства
        ("втулка 236-1007118 — что это?", "ЯМЗ-236М2", None),  # обозначение детали, не двигатель
        ("на моём МАЗ-5337 стучит", "ЯМЗ-236М2", None),  # машина, не двигатель
    ],
)
def test_other_engine_detected_by_code(question: str, engine: str, expected: str | None) -> None:
    assert other(question, engine) == expected


def test_not_in_base_clean_refusal_without_numbers(ml: MLClient, toir: ToirClient) -> None:
    ag, llm = make_agent([say("Зазор 0,25-0,30 мм.")], ml, toir)
    reply = ag.ask(ag.start("B418HK98", "S-0007"), "А у ЯМЗ-7511 какой зазор клапанов?")
    assert reply.text.startswith("**Руководств на ЯМЗ-7511 в базе нет.**") and "ЯМЗ-236М2" in reply.text
    assert not re.search(r"\d+[.,]\d+|\d+\s*(?:мм|Н·м|кПа)", reply.text)  # ни одной цифры с единицами
    assert not llm.seen and reply.trace["cost_rub"] == 0 and reply.sources == []


def test_engine_of_other_fleet_vehicle_points_to_that_vehicle(ml: MLClient, toir: ToirClient) -> None:
    ag, llm = make_agent([say("ответ")], ml, toir)
    reply = ag.ask(ag.start("B418HK98", "S-0007"), "А на ЗМЗ-5234 какой зазор?")
    assert "Вопрос про ЗМЗ-5234" in reply.text and "откройте машину с этим двигателем" in reply.text
    assert not llm.seen


def test_own_engine_goes_to_model(ml: MLClient, toir: ToirClient) -> None:
    ag, llm = make_agent([say("Ответ по руководству.")], ml, toir)
    ag.ask(ag.start("B418HK98", "S-0007"), "Какой зазор клапанов на ЯМЗ-236?")
    assert llm.seen
