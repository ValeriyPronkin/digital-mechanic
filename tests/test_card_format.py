"""Ответ о неисправности из карточки — разделами интерфейса v2 при любом уровне механика (verify_explain 27.11).

B418HK98 / S-0009 (видео, подтверждённая ячейка матрицы): кнопка «Получить результат диагностики» давала голый порядок
регулировки зазоров без «Что это может быть / Чем это грозит / Что проверить». A427MA78 / S-0032: в «Чем это грозит» —
оценка инженера из справочника классов опасности без страницы и без пометки (инвариант 4)."""

from __future__ import annotations

import pytest

from service.agent import CARD_FORMAT, ENGINEER_MARK, SECTIONS, mark_risk, section_heads
from service.clients import MLClient, ToirClient
from test_agent import make_agent, say


@pytest.mark.parametrize("vehicle", [("B418HK98", "S-0009"), ("A427MA78", "S-0032")])
@pytest.mark.parametrize("level", ["auto", "master", "mechanic", "novice"])
def test_diagnosis_button_asks_for_sections_at_any_level(
    ml: MLClient, toir: ToirClient, vehicle: tuple[str, str], level: str
) -> None:
    ag, llm = make_agent([say("Что слышно\nЦокот.")], ml, toir)
    ag.ask(ag.start(*vehicle), "Получить результат диагностики", level=level)
    first_user = next(m for m in llm.seen[0] if m["role"] == "user")
    assert CARD_FORMAT in str(first_user["content"])


def test_direct_question_has_no_card_format(ml: MLClient, toir: ToirClient) -> None:
    ag, llm = make_agent([say("Зазор 0,25–0,30 мм [R1].")], ml, toir)
    ag.ask(ag.start("B418HK98", "S-0009"), "Какой тепловой зазор клапанов?")
    assert CARD_FORMAT not in str(next(m for m in llm.seen[0] if m["role"] == "user")["content"])


def test_sections_match_the_interface() -> None:
    import re
    from pathlib import Path

    copy = Path(__file__).resolve().parents[1].joinpath("web", "src", "copy.ts").read_text(encoding="utf-8")
    block = copy[copy.index("sections: [") : copy.index("]", copy.index("sections: ["))]
    assert tuple(re.findall(r"'([^']+)'", block)) == SECTIONS


def test_inline_bold_heading_becomes_its_own_line() -> None:
    text = "**Что слышно:** ритмичный цокот.\n### Что это может быть\n- Зазор увеличен [R1].\nЧем это грозит:"
    assert section_heads(text) == (
        "Что слышно\nритмичный цокот.\nЧто это может быть\n- Зазор увеличен [R1].\nЧем это грозит"
    )


def test_risk_without_page_is_marked_as_engineer_assessment() -> None:
    """A427MA78: «задир поршней…» из справочника классов опасности — без страницы, значит с пометкой."""
    text = (
        "Чем это грозит\nПрямого указания о последствиях в руководстве нет.\n- Задир поршней и заклинивание.\n"
        "- Падение давления масла [R2].\nЧто проверить\n1. Уровень масла."
    )
    out = mark_risk(text)
    assert f"- Задир поршней и заклинивание {ENGINEER_MARK}." in out
    assert "- Падение давления масла [R2]." in out and "Прямого указания о последствиях в руководстве нет." in out
    assert "1. Уровень масла." in out  # вне раздела — не трогаем


def test_agent_answer_keeps_sections_and_marks_risk(ml: MLClient, toir: ToirClient) -> None:
    answer = (
        "**Что слышно:** ритмичный цокот в головках.\n**Что это может быть:** увеличенный зазор клапанов.\n"
        "**Чем это грозит:** прогар клапана.\n**Что проверить:**\n1. Проверить зазоры."
    )
    ag, _ = make_agent([say(answer)], ml, toir)
    text = ag.ask(ag.start("B418HK98", "S-0009"), "Получить результат диагностики").text
    for name in ("Что слышно", "Что это может быть", "Чем это грозит", "Что проверить"):
        assert f"\n{name}\n" in f"\n{text}\n", name
    assert f"прогар клапана {ENGINEER_MARK}." in text


def test_failed_recording_does_not_open_the_manuals(ml: MLClient, toir: ToirClient) -> None:
    """Sweep 27.11: на «Создать заявку» после сбоя записи модель искала по руководству (3 из 5 нитей). Поиск по такой
    проверке отклоняется с объяснением; руководство не открывается, страниц в ответе нет."""
    from service.agent import CHECK_FAILED_NO_SEARCH
    from test_agent import call, first

    failed = first(lambda v, s: s.status == "check_failed")
    steps = [call("search_manual", query="заявка на дефектовку"), say("Запись не годится, повторите проверку.")]
    ag, llm = make_agent(steps, ml, toir)
    conv = ag.start(*failed)
    ag._ensure_diag(conv)
    reply = ag.ask(conv, "Создать заявку")
    tool = next(m for m in llm.seen[-1] if m["role"] == "tool" and m.get("name") == "search_manual")
    assert CHECK_FAILED_NO_SEARCH in str(tool["content"]) and reply.sources == [] and reply.draft is None


def test_mismatch_answer_names_both_ways(ml: MLClient, toir: ToirClient) -> None:
    """golden mismatch-insist-536: на «свечи всё равно надо посмотреть» у дизеля — посторонний порядок работ без
    «повторить проверку» и «дефектовка». Код дописывает оба пути; если они уже есть — не дублирует."""
    from service.agent import MISMATCH_STEPS

    ag, _ = make_agent([say("Свечей на этом двигателе нет.\n\n1. Снимите крышку головки [R1].")], ml, toir)
    conv = ag.start("K354KC98", "S-0087")
    _, card = ag._ensure_diag(conv)
    assert card.status == "anomaly" and not card.compatible
    text = ag.ask(conv, "Свечи всё равно надо посмотреть. Какой зазор?").text
    assert text.endswith(MISMATCH_STEPS)
    ag, _ = make_agent([say("Свечей нет. Повторите проверку; если стук остаётся — дефектовка узла.")], ml, toir)
    assert MISMATCH_STEPS not in ag.ask(ag.start("K354KC98", "S-0087"), "А свечи?").text


def test_failed_recording_gets_no_search_tool(ml: MLClient, toir: ToirClient) -> None:
    from test_agent import first

    failed = first(lambda v, s: s.status == "check_failed")
    ag, _ = make_agent([], ml, toir)
    conv = ag.start(*failed)
    ag._ensure_diag(conv)
    names = {t.name for t in ag._tools_for(conv)}
    assert "search_manual" not in names and "read_pages" not in names and "get_diagnosis" in names
