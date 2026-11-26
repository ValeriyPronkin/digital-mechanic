"""Чистый отказ (независимый прогон 26.11, п. 5): «в руководстве нет» — без чисел с единицами рядом."""

from __future__ import annotations

from service.clean_refusal import NOTE, clean, is_refusal
from service.clients import MLClient, ToirClient
from test_agent import make_agent, say

REFUSAL = (
    "В таблице моментов затяжки этого двигателя строки «гайки стоек оси коромысел» нет — в руководстве не нашёл. "
    "Есть только близкие значения: болты крышек распредвалов 18,6…22,6 Н·м [R1].\n\n"
    "1. Не затягивайте «на глаз».\n2. Проверьте болты крышки клапанов 6,9…8,8 Н·м [R1].\n3. Оформите дефектовку."
)


def test_refusal_drops_values_with_units_keeps_steps() -> None:
    text, removed = clean(REFUSAL)
    assert removed and "Н·м" not in text and "18,6" not in text
    assert "в руководстве не нашёл" in text and "1. Не затягивайте" in text and "3. Оформите дефектовку." in text


def test_positive_answer_untouched() -> None:
    answer = "**Зазор 0,25–0,30 мм** [R1].\n\n1. Щуп 0,25 мм входит с лёгким нажимом [R1]."
    assert clean(answer) == (answer, False)


def test_refusal_detected_only_in_direct_answer() -> None:
    assert is_refusal("В найденных фрагментах значения нет.\n\n1. Шаг.")
    assert not is_refusal("Зазор 0,25 мм [R1].\n\nЕсли в руководстве нет вашей модификации — к специалисту.")


def test_agent_refusal_is_clean(ml: MLClient, toir: ToirClient) -> None:
    answer = "В руководстве не нашёл момент для этой гайки. Есть давление масла 0,4–0,7 МПа [R1].\n\n1. К специалисту."
    ag, _ = make_agent([say(answer)], ml, toir)
    reply = ag.ask(ag.start("B418HK98", "S-0007"), "Какой момент гайки?")
    assert "МПа" not in reply.text and "1. К специалисту." in reply.text and NOTE in reply.notes
