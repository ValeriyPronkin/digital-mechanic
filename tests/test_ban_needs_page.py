"""Запрет эксплуатации — только словами руководства и с его страницей; приоритет — рекомендация (ответ организаторов
26.11). Строка «Безопасность» — только когда руководство что-то говорит о безопасности."""

from __future__ import annotations

from service.agent import LEVEL_PROMPT, NO_BAN_LINE, RECOMMEND, SYSTEM_PROMPT, Source, unsourced_bans
from service.clients import MLClient, ToirClient
from service.verdict_policy import URGENCY_ACTION
from test_agent import ANOMALY, make_agent, say


def test_ban_without_page_becomes_recommendation() -> None:
    """Стенд 27.11, A427MA78: «Нет, своим ходом ехать нельзя… прямого запрета в руководстве нет» и шаг «эвакуатор»."""
    answer = (
        "Нет, своим ходом ехать нельзя. Давление масла ниже нормы [R1].\n\n"
        "1. Заглушите двигатель [R1].\n2. Перевозите машину на буксире или эвакуаторе.\n"
        "3. Проверьте уровень масла [R2]."
    )
    text, removed = unsourced_bans(answer, "high")
    assert removed == 2 and "нельзя" not in text and "эвакуатор" not in text
    assert text.startswith(f"{NO_BAN_LINE} {RECOMMEND['high']} Давление масла ниже нормы [R1].")
    assert "1. Заглушите двигатель [R1].\n3. Проверьте уровень масла [R2]." in text


def test_ban_with_its_page_stays() -> None:
    answer = "Эксплуатация двигателя при давлении ниже 100 кПа не допускается [R3]."
    assert unsourced_bans(answer, "high") == (answer, 0)


def test_other_prohibitions_are_not_operation_bans() -> None:
    answer = "Болты маховика нельзя ставить повторно."  # не о выезде — не трогаем
    assert unsourced_bans(answer, "high") == (answer, 0)


def test_empty_safety_line_is_dropped_real_one_kept() -> None:
    text, _ = unsourced_bans("Понадобится: ключ.\nБезопасность: в руководстве не указано.\n\n1. Шаг [R1].", None)
    assert "Безопасность" not in text and text.startswith("Понадобится: ключ.\n\n1. Шаг")
    kept = "Безопасность: двигатель заглушён и остыл [R1].\n\n1. Шаг [R1]."
    assert unsourced_bans(kept, None) == (kept, 0)
    assert "если их нет — строку не пиши" in LEVEL_PROMPT["steps"]


def test_agent_answer_and_ticket_conclusion_have_no_unsourced_ban(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Нет, ехать нельзя до дефектовки. Давление масла [R1].")], ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Можно ли ехать своим ходом?")
    assert "ехать нельзя" not in reply.text and NO_BAN_LINE in reply.text
    conv = ag.start(*ANOMALY)
    conv.sources["R1"] = Source(ref="R1", manual_id="yamz-236-re", manual="РЭ", pdf_page=30, section="",
                                text="Проверить давление масла по указателю.")  # fmt: skip
    res = ag._draft_ticket(conv, {"conclusion": "Эксплуатировать нельзя. Низкое давление масла.",
                                  "operations": [{"text": "Проверить давление масла", "ref": "R1"}]})  # fmt: skip
    assert res["draft"]["conclusion"] == "Низкое давление масла."


def test_card_action_is_a_recommendation_not_a_ban() -> None:
    high = URGENCY_ACTION["high"]
    assert "не эксплуатировать" not in high and "до выпуска в рейс" in high
    assert "только словами руководства и со ссылкой" in SYSTEM_PROMPT
    assert "напиши «в руководстве не нашёл»" not in SYSTEM_PROMPT
