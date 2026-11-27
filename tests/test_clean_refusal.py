"""Чистый отказ (независимый прогон 26.11, п. 5): «в руководстве нет» — без чисел с единицами рядом."""

from __future__ import annotations

from service.clean_refusal import NOTE, clean, complete, drop_specialist, is_refusal, unnumber_gaps
from service.clients import MLClient, ToirClient
from test_agent import ANOMALY, make_agent, say

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


def test_service_lines_are_not_refusal() -> None:
    """eval Q16: «Безопасность: в руководстве не указано» в первом абзаце — не отказ."""
    text = "Понадобится: ключ.\nБезопасность: в руководстве не указано.\n\n1. Довернуть на 95° [R1]."
    assert not is_refusal(text) and clean(text) == (text, False)


def test_steps_first_is_not_refusal() -> None:
    """eval Q36: после служебных строк сразу шаги — отказа нет, даже если в шаге «в руководстве нет …»."""
    text = "Безопасность: в руководстве не указано.\n\n1. Момент 70,6…78,4 Н·м [R1]; в руководстве нет других."
    assert not is_refusal(text)


def test_refusal_detected_only_in_direct_answer() -> None:
    assert is_refusal("В найденных фрагментах значения нет.\n\n1. Шаг.")
    assert not is_refusal("Зазор 0,25 мм [R1].\n\nЕсли в руководстве нет вашей модификации — к специалисту.")


def test_agent_refusal_is_clean(ml: MLClient, toir: ToirClient) -> None:
    answer = "В руководстве не нашёл момент для этой гайки. Есть давление масла 0,4–0,7 МПа [R1].\n\n1. На дефектовку."
    ag, _ = make_agent([say(answer)], ml, toir)
    reply = ag.ask(ag.start("B418HK98", "S-0007"), "Какой момент гайки?")
    assert "МПа" not in reply.text and "Что сделать: на дефектовку." in reply.text and NOTE in reply.notes
    assert "1. " not in reply.text  # шаг без ссылки на руководство — не нумерованный


def test_specialist_advice_dropped_but_manual_quote_kept() -> None:
    """Правило заказчика 27.11: механик сам специалист — «к специалисту» без ссылки убирается."""
    text, removed = drop_specialist("В руководстве нет. Обратитесь к специалисту.\n«Ремонт выполняет специалист» [R2].")
    assert removed and "Обратитесь" not in text and "[R2]" in text


def test_refusal_gets_action_and_nearest_page() -> None:
    text, added = complete(
        "В руководстве на ЯМЗ-236М2 этого нет.", "Что сделать: дефектовка.", "Ближе всего: стр. 5 [R3]."
    )
    assert added == ["Что сделать: дефектовка.", "Ближе всего: стр. 5 [R3]."] and text.endswith("[R3].")
    # действие уже есть — второй раз не дописывается; положительный ответ не трогается
    assert complete("В руководстве нет. Нужна дефектовка насоса.", "Что сделать: X.", None) == (
        "В руководстве нет. Нужна дефектовка насоса.",
        [],
    )
    assert complete("Зазор 0,25 мм [R1].", "Что сделать: X.", "Ближе: Y")[1] == []
    # частичный ответ со ссылками (eval Q36: «прямо названы только болты маховика [R10]») — не дописывается
    assert complete("В найденных фрагментах нет запрета.\n\n1. Болты маховика — новые [R10].", "X", "Y")[1] == []


def test_agent_refusal_names_node_and_nearest_page(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("В руководстве на этот двигатель этого нет. Обратитесь к специалисту.")], ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Что делать, почему давление падает?")
    assert "специалист" not in reply.text
    assert "Что сделать: дефектовка узла по неисправности" in reply.text and "F02" not in reply.text  # без кода
    near = reply.sources[-1]  # ближайшая страница этого двигателя из поиска — в источниках ответа
    assert f"Ближе всего в руководстве на ЯМЗ-236М2: «{near['section']}», стр. {near['pdf_page']}" in reply.text


def test_refusal_off_card_question_names_question_node(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("В руководстве на этот двигатель этого нет.")], ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Какой момент затяжки гайки шкива?")
    assert "Что сделать: дефектовка узла, о котором вопрос." in reply.text and "F02" not in reply.text


# ---------- совет без ссылки — не нумерованный шаг (приёмщик 27.11) ----------


def test_gap_steps_leave_numbering() -> None:
    text = (
        "Ездить нельзя [R1].\n\n1. Заглушить двигатель [R1].\n2. Проверить уровень масла [R2].\n"
        "3. Для болтов коренных примечания нет — уточните у производителя двигателя.\n4. Затянуть болты [R2].\n"
        "5. Порядка работ по этому узлу в руководстве нет — нужна дефектовка.\n\nПонадобится: щуп."
    )
    out, n = unnumber_gaps(text)
    assert n == 2
    assert "1. Заглушить двигатель [R1].\n2. Проверить уровень масла [R2].\n3. Затянуть болты [R2].\n\n" in out
    assert "\nЧто сделать: для болтов коренных примечания нет — уточните у производителя двигателя." in out
    assert "4. " not in out and "5. " not in out and out.endswith("Понадобится: щуп.")


def test_steps_with_refs_and_plain_steps_kept() -> None:
    text = "Зазор 0,25 мм [R1].\n\n1. Снять крышки.\n2. Провернуть коленвал [R1]."
    assert unnumber_gaps(text) == (text, 0)  # шаг процедуры без пробела руководства — остаётся шагом


def test_full_refusal_without_refs_has_no_numbered_steps() -> None:
    text = "В руководстве порядка нет.\n\n1. Заглушите двигатель.\n2. Организуйте перевозку на базу."
    out, n = unnumber_gaps(text)
    assert n == 2
    assert out == "В руководстве порядка нет.\n\nЧто сделать: заглушите двигатель. Организуйте перевозку на базу."


def test_no_label_for_other_language_and_abbreviation_kept() -> None:
    out, _ = unnumber_gaps("Жавоб [R1].\n\n1. Қадам [R1].\n2. «в руководстве не нашёл» — дефектовка.", label="")
    assert out.endswith("1. Қадам [R1].\n\n«в руководстве не нашёл» — дефектовка.")
    out, _ = unnumber_gaps("Ответ [R1].\n\n1. ТНВД — уточните у производителя.")
    assert out.endswith("Что сделать: ТНВД — уточните у производителя.")
