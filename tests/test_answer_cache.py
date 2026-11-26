"""Кэш ответов (issue #16): тот же вопрос + тот же двигатель и результат проверки → 0 токенов."""

from __future__ import annotations

import pytest

import service.agent as agent_mod
from service.agent import Agent
from service.clients import MLClient, ToirClient
from test_agent import ANOMALY, NORMAL, ScriptedLLM, make_agent, say

Q = "Что с двигателем?"


def _two(ml: MLClient, toir: ToirClient, first: tuple[str, str], second: tuple[str, str], q2: str = Q) -> tuple:
    ag, llm = make_agent([say("Давление масла ниже нормы [R1]."), say("Другой ответ.")], ml, toir)
    r1 = ag.ask(ag.start(*first), Q)
    r2 = ag.ask(ag.start(*second), q2)
    return ag, llm, r1, r2


def test_same_question_same_check_comes_from_cache(ml: MLClient, toir: ToirClient) -> None:
    _, llm, r1, r2 = _two(ml, toir, ANOMALY, ANOMALY, q2="  что с ДВИГАТЕЛЕМ!! ")
    assert len(llm.seen) == 1  # второй раз модель не вызывалась
    assert r2.trace["cache"] and r2.trace["cost_rub"] == 0 and r2.trace["tokens_in"] == 0
    assert r2.text == r1.text and r2.sources == r1.sources and r2.grounded


def test_other_result_is_not_taken_from_cache(ml: MLClient, toir: ToirClient) -> None:
    _, llm, _, r2 = _two(ml, toir, ANOMALY, NORMAL)
    assert len(llm.seen) == 2 and not r2.trace.get("cache")


def test_ticket_and_followups_are_not_cached(ml: MLClient, toir: ToirClient) -> None:
    ag, llm = make_agent([say("А."), say("Б."), say("В."), say("Г.")], ml, toir)
    c1 = ag.start(*ANOMALY)
    ag.ask(c1, Q)
    ag.ask(c1, "А что проверить?")
    c2 = ag.start(*ANOMALY)
    ag.ask(c2, "Оформи заявку")
    r = ag.ask(c2, "А что проверить?")  # второй вопрос разговора — не из кэша
    assert len(llm.seen) == 4 and not r.trace.get("cache")


def test_new_index_or_matrix_drops_cache(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    ag, llm = make_agent([say("А [R1]."), say("Б.")], ml, toir)
    ag.ask(ag.start(*ANOMALY), Q)
    monkeypatch.setattr(agent_mod, "knowledge_version", lambda: "новый-индекс")
    r = ag.ask(ag.start(*ANOMALY), Q)
    assert len(llm.seen) == 2 and not r.trace.get("cache")


def test_cached_sources_are_usable_in_followup(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Давление масла ниже нормы [R1].")], ml, toir)
    ag.ask(ag.start(*ANOMALY), Q)
    conv = ag.start(*ANOMALY)
    hit = ag.ask(conv, Q)
    assert hit.trace["cache"] and "R1" in conv.sources
    assert isinstance(ag, Agent) and isinstance(ag.provider, ScriptedLLM)


def test_cached_answer_does_not_overwrite_sources_of_this_conversation(ml: MLClient, toir: ToirClient) -> None:
    """Номера R… из кэша — чужие: страница этого разговора под тем же номером не затирается (чип не врёт)."""
    from service.agent import Source, next_ref

    ag, _ = make_agent([], ml, toir)
    conv = ag.start(*ANOMALY)
    conv.sources = {
        "R1": Source("R1", "yamz-236-re", "РЭ", 57, "ТО", "Первое техническое обслуживание (ТО-1)"),
        "R3": Source("R3", "yamz-236-re", "РЭ", 31, "Клапаны", "Тепловой зазор 0,25-0,30 мм"),
    }
    hit = {
        "text": "Регулировать на холодном двигателе [R1]; зазор 0,25-0,30 мм [R2].",
        "grounded": True,
        "notes": [],
        "sources": [
            {
                "ref": "R1",
                "manual_id": "yamz-236-rk",
                "manual": "РК",
                "pdf_page": 276,
                "section": "6.5",
                "text": "Проверку",
            },
            {
                "ref": "R2",
                "manual_id": "yamz-236-re",
                "manual": "РЭ",
                "pdf_page": 31,
                "section": "Клапаны",
                "text": "0,25",
            },
        ],
    }
    reply = ag._reply_from_cache(conv, hit, "req")
    assert (conv.sources["R1"].manual_id, conv.sources["R1"].pdf_page) == ("yamz-236-re", 57)  # не затёрт
    by_page = {(s.manual_id, s.pdf_page): s.ref for s in conv.sources.values()}
    new = by_page[("yamz-236-rk", 276)]
    assert new == "R4"  # следующий после максимального, а не «число источников + 1» (= R3, занят)
    assert f"[{new}]" in reply.text and "[R3]" in reply.text  # стр. 31 уже была в разговоре — её номер
    assert next_ref(conv) == "R5"
