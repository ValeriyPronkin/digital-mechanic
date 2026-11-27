"""Число — из источника своего предложения (как verify.py Никиты), а не из любого источника ответа."""

from __future__ import annotations

import pytest

from service.agent import Source
from service.clients import MLClient, ToirClient
from test_agent import ANOMALY, make_agent


def _conv(ml: MLClient, toir: ToirClient):  # type: ignore[no-untyped-def]
    ag, _ = make_agent([], ml, toir)
    conv = ag.start(*ANOMALY)
    for ref, page, text in (("R1", 10, "Давление масла 4,0 кгс/см2"), ("R2", 50, "Момент затяжки 120 Н·м"),
                            ("R3", 11, "Зазор 0,25 мм")):  # fmt: skip
        conv.sources[ref] = Source(ref=ref, manual_id="yamz-236-rk", manual="РК", pdf_page=page, section="", text=text)
    return ag, conv


def test_number_from_other_source_dropped(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GUARD_OWN_SOURCE", raising=False)
    ag, conv = _conv(ml, toir)
    text, *_ = ag.guard(conv, "Давление масла 120 кгс/см2 [R1]. Момент затяжки 120 Н·м [R2].")
    assert "Давление масла 120" not in text and "Момент затяжки 120 Н·м" in text
    assert conv.passport["guard"]["own_source_dropped"] == 1


def test_neighbour_page_and_unmarked_sentence_kept(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GUARD_OWN_SOURCE", raising=False)
    ag, conv = _conv(ml, toir)
    answer = "Зазор 0,25 мм и давление 4,0 кгс/см2 [R1].\nПотом момент 120 Н·м.\nЩупом [R3]. Ключом [R2]."
    text, *_ = ag.guard(conv, answer)
    assert "0,25" in text  # стр. 11 — соседняя со стр. 10: переход через разрыв страницы
    assert "120 Н·м" in text  # без ссылки в предложении и строке — по всем источникам, как раньше


def test_switch_off(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUARD_OWN_SOURCE", "0")
    ag, conv = _conv(ml, toir)
    text, *_ = ag.guard(conv, "Давление масла 120 кгс/см2 [R1]. Момент затяжки 120 Н·м [R2].")
    assert "Давление масла 120" in text
