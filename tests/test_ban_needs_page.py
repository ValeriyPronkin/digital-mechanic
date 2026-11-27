"""Запрет эксплуатации — только словами руководства и с его страницей; приоритет — рекомендация (ответ организаторов
26.11). Строка «Безопасность» — только когда руководство что-то говорит о безопасности."""

from __future__ import annotations

from service.agent import LEVEL_PROMPT, NO_BAN_LINE, RECOMMEND, SYSTEM_PROMPT, Source, unsourced_bans
from service.clients import MLClient, ToirClient
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
    assert "если их нет — строку не пиши" in LEVEL_PROMPT["novice"]


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


def test_prompt_bans_only_with_a_page() -> None:
    assert "только словами руководства и со ссылкой" in SYSTEM_PROMPT
    assert "напиши «в руководстве не нашёл»" not in SYSTEM_PROMPT


def test_internal_words_and_codes_are_not_shown() -> None:
    """Стенд 27.11: «(матрица silent)», «из ссылок R12, R8, R1», «код F07» — служебное, механик их не читает."""
    from service.agent import plain_words

    assert plain_words("В руководстве нет порядка работ (матрица silent). Дефектовка [R2].", None) == (
        "В руководстве нет порядка работ. Дефектовка [R2]."
    )
    assert plain_words("В заявку попали страницы из ссылок R12, R8, R1.", None) == "В заявку попали страницы."
    assert plain_words("Проверка показала код F07.", "Неисправность КПП") == "Проверка показала «Неисправность КПП»."
    assert plain_words("Неисправность F03 «Перегрев» [R1], [R2].", None) == "Неисправность «Перегрев» [R1], [R2]."


def test_no_first_person_in_code_strings() -> None:
    from service import other_engine

    text = other_engine.answer("ЗМЗ-409", "A123BC77", "ЯМЗ-236М2") + other_engine.answer("Cummins", "A1", "ЯМЗ-236М2")
    assert "Отвечаю" not in text and "могу" not in text


def test_imperative_is_polite() -> None:
    from service.agent import plain_words

    assert plain_words("Ничего не ремонтируй. Повтори проверку и убедись в записи.", None) == (
        "Ничего не ремонтируйте. Повторите проверку и убедитесь в записи."
    )
    assert plain_words("Проверьте зазор [R1].", None) == "Проверьте зазор [R1]."


def test_session_id_empty_source_and_first_person_not_shown() -> None:
    """Демо B418HK98 / S-0009: «S-0009», «F01», пустой «Источник:.», «я не нашёл» — служебное и первое лицо."""
    from service.agent import plain_words

    text = plain_words("Проверка S-0009 показала F01.\nЯ не нашёл в руководстве нормы.\n\nИсточник:.", "Клапаны")
    assert text == "Проверка показала «Клапаны».\nНе найдено в руководстве нормы."


def test_prompt_sections_match_the_interface() -> None:
    """Заголовки разделов — ровно как `sections` в web/src/copy.ts, иначе интерфейс рисует их простым текстом;
    «Чем это грозит» обязателен (ТЗ F3, С1)."""
    import re
    from pathlib import Path

    copy = Path(__file__).resolve().parents[1].joinpath("web", "src", "copy.ts").read_text(encoding="utf-8")
    block = copy[copy.index("sections: [") : copy.index("]", copy.index("sections: ["))]
    names = re.findall(r"'([^']+)'", block)
    assert "Чем это грозит" in names
    for name in names:
        assert f"«{name}" in SYSTEM_PROMPT or f"{name}»" in SYSTEM_PROMPT or f" {name} " in SYSTEM_PROMPT, name


def test_absence_claim_carries_no_page_chips(ml: MLClient, toir: ToirClient) -> None:
    """Стенд 27.11: «давления в шинах в руководстве нет [R1][R2]» с посторонними страницами и «(испытания на стенде)».
    Утверждение об отсутствии — без ссылок; страницы, на которые ничто не ссылается, уходят из источников."""
    from service.clean_refusal import unmark_absence

    text, removed = unmark_absence("Давления в шинах в руководстве этого двигателя нет [R1] [R2].\n\n1. Шаг [R3].")
    assert removed == 2 and text == "Давления в шинах в руководстве этого двигателя нет.\n\n1. Шаг [R3]."
    ag, _ = make_agent([say("В руководстве этого двигателя нет данных о шинах [R1].")], ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Какое давление в шинах?")
    assert "[R1]" not in reply.text.split("\n\n")[0] and "испытания на стенде" not in reply.text.split("\n\n")[0]
