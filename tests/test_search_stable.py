"""Стабильность поиска (штурман 26.11): план поиска — с температурой 0, иначе один вопрос давал разные страницы."""

from __future__ import annotations

from typing import Any

from service.clients import MLClient, ToirClient
from service.llm import LLMReply
from test_agent import make_agent, say


def test_search_plan_called_with_zero_temperature(ml: MLClient, toir: ToirClient) -> None:
    seen: list[Any] = []
    ag, llm = make_agent([say('{"lang":"ru","question_ru":"q","queries":["q"]}'), say("ответ")], ml, toir,
                         plan_search=True)  # fmt: skip
    orig = llm.chat

    def spy(messages: Any, tools: Any, max_tokens: Any = None, temperature: Any = None) -> LLMReply:
        seen.append(temperature)
        return orig(messages, tools, max_tokens, temperature)

    llm.chat = spy  # type: ignore[method-assign]
    ag.ask(ag.start("B418HK98", "S-0007"), "Какой зазор клапанов?")
    assert seen[0] == 0.0  # план поиска
    assert seen[-1] is None  # основной ответ — по настройке LLM_TEMPERATURE


def test_default_temperature_from_env(monkeypatch: Any) -> None:
    from service.llm import default_temperature

    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    assert default_temperature() == 0.0
    monkeypatch.setenv("LLM_TEMPERATURE", "x")
    assert default_temperature() == 0.2
