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
    _, _, r1, r2 = _two(ml, toir, ANOMALY, NORMAL)  # при норме на «Что с двигателем?» отвечает код (приёмка 27.11)
    assert not r2.trace.get("cache") and r2.text != r1.text


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


def _same_cell_other_vehicle() -> tuple[tuple[str, str], tuple[str, str]]:
    """Две машины с одним двигателем, кодом и качеством записи — ключ без машины у них совпадал."""
    from service.fleet import fleet

    seen: dict[tuple[str, str | None], tuple[str, str]] = {}
    for v in fleet().vehicles:
        for s in v.sessions:
            if s.status == "anomaly" and s.signal_quality == "good":
                cell = (v.engine_model, s.anomaly_type)
                if cell in seen and seen[cell][0] != v.vehicle_id:
                    return seen[cell], (v.vehicle_id, s.session_id)
                seen.setdefault(cell, (v.vehicle_id, s.session_id))
    raise AssertionError("в данных нет двух машин с одной ячейкой")


def test_answer_of_other_vehicle_is_not_served(ml: MLClient, toir: ToirClient) -> None:
    """Ревью 27.11: та же ячейка «двигатель × код × запись» у другой машины отдавала чужой ответ слово в слово."""
    a, b = _same_cell_other_vehicle()
    _, llm, r1, r2 = _two(ml, toir, a, b)
    assert len(llm.seen) == 2 and not r2.trace.get("cache")
    assert r2.text != r1.text


def test_confidence_and_trend_of_other_truck_do_not_leak(ml: MLClient, toir: ToirClient) -> None:
    """Повтор ревью: T792HO98/S-0043 (уверенность 91 %, тенденция до 0,85), затем E549YT198/S-0011 (84 %)."""
    ag, llm = make_agent([say("Уверенность проверки 91%. Давление масла ниже нормы [R1]."), say("Другой ответ.")],
                         ml, toir)  # fmt: skip
    ag.ask(ag.start("T792HO98", "S-0043"), Q)
    r2 = ag.ask(ag.start("E549YT198", "S-0011"), Q)
    assert len(llm.seen) == 2 and not r2.trace.get("cache")
    assert "91" not in r2.text and "0,85" not in r2.text


def test_new_ticket_on_vehicle_drops_cached_answer(ml: MLClient, toir: ToirClient) -> None:
    """Ответ видит заявки машины, отправленные ранее (контекст разговора): новая заявка — новый ответ."""
    ag, llm = make_agent([say("А [R1]."), say("Б.")], ml, toir)
    ag.ask(ag.start(*ANOMALY), Q)
    ag.store.remember_ticket("T-1", {"vehicle_id": ANOMALY[0], "session_id": ANOMALY[1], "anomaly_type": "F02",
                                     "urgency": "high", "operations": [], "references": []}, "fp")  # fmt: skip
    r = ag.ask(ag.start(*ANOMALY), Q)
    assert len(llm.seen) == 2 and not r.trace.get("cache")


def test_knowledge_version_follows_the_build_and_the_conflict_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Финальная проверка 27.11: правка кода или data/contradictions.json без пересборки индекса — кэш отдавал
    прежний ответ. Теперь в версии знаний — сборка (GIT_SHA) и отметки этих файлов."""
    from service import agent as agent_mod

    monkeypatch.setenv("GIT_SHA", "aaa")
    a = agent_mod.knowledge_version()
    monkeypatch.setenv("GIT_SHA", "bbb")
    assert agent_mod.knowledge_version() != a
    assert agent_mod.knowledge_version().count("/") >= 5  # сборка + индекс, матрица, противоречия, код
