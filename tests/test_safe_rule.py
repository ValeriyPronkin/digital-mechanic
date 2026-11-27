"""Безопасное правило при противоречии руководств (ответы организаторов 27.11): обе формулировки со страницами и
правило, выведенное из самих страниц; отсылки «к специалисту / производителю / главному механику» нет.

Порядок правил: страница отсылает к разделу → действует он; значения совпадают в основной единице и расходятся только
в пересчёте → совпадают; диапазоны пересекаются → укладываться в оба, каждый целиком со страницей; иначе — значение
приложения, при сомнении — дефектовка узла. Общий диапазон правило не составляет."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from service import agent as agent_mod
from service.clean_refusal import drop_specialist
from service.contradictions import RULE, Known, block, check_model_blocks, derive, known, safe_rule

P41 = ("затяжку болтов крепления крышек коренных подшипников и стяжных болтов блока производить в соответствии с "
       "моментом, указанном в разделе\nСборка двигателя: затяжку болтов крепления крышек производить с моментом\n"
       "421-461 Н*м (43-47 кгс*м) последовательно в два приема")  # fmt: skip
P248 = ("5.2.9 Крышки коренных подшипников\n- затянуть болты крепления крышек коренных подшипников не менее,\n"
        "чем в три приема, моментом силы от 421 до 461 Нм (от 42 до 46 кгс·м);\nПри этом, на каждом этапе болты "
        "затягивать в следующей очередности:\n- вторая опора, третья, первая и четвертая опоры – для шестицилиндро-\n"
        "вых двигателей;")  # fmt: skip
PAGES = {
    ("yamz-236-rk", 41): P41,
    ("yamz-236-rk", 56): "должны быть затянуты моментом силы от 421 до 461 Н·м ( от 43 до 47 кгс·м)",
    ("yamz-236-rk", 248): P248,
    ("yamz-236-rk", 286): "Болты крепления крышек коренных\nподшипников:\n вертикальные 430-470 (43-47)",
}


def page_text(doc: str, page: int) -> str | None:
    return PAGES.get((doc, page))


def main_bearing() -> Known:
    return next(k for k in known() if k.id == "yamz-236-main-bearing-torque")


def test_page_that_refers_to_a_section_gives_the_rule_of_that_section() -> None:
    """ЯМЗ-236, коренные: стр. 41 отсылает к «Сборка двигателя» — действует стр. 248 (ответ организаторов 27.11)."""
    k = main_bearing()
    rule = safe_rule(k, list(k.quotes), page_text)
    assert rule.startswith("РК, стр. 41 отсылает к разделу «Сборка двигателя» — действует он (РК, стр. 248)")
    assert "не менее, чем в три приема" in rule and "от 421 до 461 Нм" in rule
    assert "«вторая опора, третья, первая и четвертая опоры»" in rule  # очерёдность — словами страницы
    assert "совпадает (РК, стр. 41, 56, 248); расходится только пересчёт" in rule  # 43-47 против 42-46 кгс·м
    assert "430" not in rule and "производител" not in rule and "специалист" not in rule


def test_reference_not_on_the_page_is_not_trusted() -> None:
    """Слова отсылки сверяются со страницей: нет их — правило выводится из значений (здесь диапазоны пересекаются)."""
    k = main_bearing()
    pages = dict(PAGES)
    pages[("yamz-236-rk", 41)] = "затяжку болтов крепления крышек производить с моментом 421-461 Н*м (43-47 кгс*м)"
    rule = safe_rule(k, list(k.quotes), lambda d, p: pages.get((d, p)))
    assert "отсылает" not in rule
    assert rule.startswith("держите значение в пределах всех диапазонов сразу:")


def test_same_value_in_main_unit_differs_only_in_conversion() -> None:
    rule = derive([
        ("с моментом 421-461 Н*м (43-47 кгс*м)", "РК", "41"),
        ("моментом силы от 421 до 461 Нм (от 42 до 46 кгс·м)", "РК", "248"),
    ])  # fmt: skip
    assert rule.startswith("в Н·м значения совпадают — 421-461 Н·м (РК, стр. 41, 248)")
    assert "расходится только пересчёт" in rule


def test_overlapping_ranges_are_named_whole_never_composed() -> None:
    rule = derive([
        ("моментом от 421 до 461 Н·м (от 43 до 47 кгс·м)", "РК", "56"),
        ("вертикальные 430-470 (43-47)", "РК", "286"),
    ])  # fmt: skip
    assert "от 421 до 461 (РК, стр. 56)" in rule and "430-470 (РК, стр. 286)" in rule
    # общий диапазон 430–461 — новое число, которого нет ни на одной странице
    assert not re.search(r"430\s*[-–…]\s*461", rule)


def test_disjoint_values_take_the_appendix_value() -> None:
    rule = derive([("Болты крепления рампы 45 ± 2 (4,5 ± 0,2)", "РЭ", "274"), ("рампы 22-25 (S=13)", "РК", "585")],
                  appendix={("РЭ", "274")})  # fmt: skip
    assert rule == "значение приложения — 45 ± 2 (РЭ, стр. 274); при сомнении — дефектовка узла."


def test_disjoint_values_two_appendices_ask_for_defect_inspection() -> None:
    rule = derive([("Болты крепления рампы 45 ± 2 (4,5 ± 0,2)", "РЭ", "274"), ("рампы 22-25 (S=13)", "РК", "585")],
                  appendix={("РЭ", "274"), ("РК", "585")})  # fmt: skip
    assert "дефектовку" in rule and not re.search(r"\d", rule)  # ни одно значение не выбрано, новых чисел нет


def test_known_items_have_a_rule_and_no_hand_off() -> None:
    for k in known():
        text = block(k, list(k.quotes), {}, page_text)
        last = text.split("\n")[-1]
        assert last.startswith("Вывод:" if k.conclusion else RULE), k.id
        assert not re.search(r"уточните|специалист|производител|главн\w* механик", text, re.I), k.id


def test_customer_rule_is_kept() -> None:
    k = next(k for k in known() if k.conclusion)
    assert block(k, list(k.quotes), {}, page_text).split("\n")[-1] == f"Вывод: {k.conclusion} Основание — {k.basis}."


def test_model_block_gets_the_derived_rule_instead_of_its_own_advice() -> None:
    sources = {"R1": PAGES[("yamz-236-rk", 56)], "R2": PAGES[("yamz-236-rk", 286)]}
    text = ("Ответ.\n\nПротиворечие в документации:\n- «должны быть затянуты моментом силы от 421 до 461 Н·м» [R1]\n"
            "- «вертикальные 430-470 (43-47)» [R2]\nБезопасное правило: 430-461 Н·м.\n"
            "Для вашей модификации уточните у производителя двигателя.")  # fmt: skip
    out, notes = check_model_blocks(text, sources.get)
    assert not notes and "уточните" not in out and "430-461" not in out
    assert f"{RULE} держите значение в пределах всех диапазонов сразу: от 421 до 461 ([R1]) и 430-470 ([R2])." in out


def test_hand_off_phrases_are_dropped_from_any_answer() -> None:
    phrases = (
        "Уточните у производителя двигателя.",
        "Обратитесь к главному механику за решением.",
        "Для вашей модификации уточните момент у завода-изготовителя.",
        "Проконсультируйтесь с дилером.",
        "Сообщите главному механику: это ошибка сервиса.",  # стенд 27.11, C808CM178
    )
    for phrase in phrases:
        text, removed = drop_specialist(f"Зазор 0,25 мм [R1]. {phrase}")
        assert removed and text == "Зазор 0,25 мм [R1].", phrase
    kept = "Передано главному механику на решение (№ 1). Пока — безопасное правило: по выводу выше."
    assert drop_specialist(kept) == (kept, False)  # строка эскалации (#93) — не отсылка механика


def test_opinion_with_manufacturer_advice_is_replaced_by_defect_inspection() -> None:
    text = agent_mod._restrict_opinions(f"Шаг [R1].\nУточните у производителя {agent_mod.OPINION_MARK}.")
    assert "производител" not in text and agent_mod.OPINION_GENERIC in text


def test_prompt_has_no_hand_off() -> None:
    assert "уточнить у производителя" not in agent_mod.SYSTEM_PROMPT
    assert "Безопасное правило к ним добавит код" in agent_mod.SYSTEM_PROMPT


INDEX = Path(os.environ.get("INDEX_DIR", ".index"))


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_main_bearing_rule_on_real_index() -> None:
    from service.manual_search import default_searcher

    pt = getattr(default_searcher(), "page_text", None)
    k = main_bearing()
    rule = safe_rule(k, list(k.quotes), pt)
    assert "отсылает к разделу «Сборка двигателя»" in rule and "вторая опора" in rule
