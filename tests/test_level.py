"""Уровень механика (#17): формат и длина ответа задаёт уровень; правила кода — те же."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from service import main
from service.agent import LEVEL_MAX_TOKENS, LEVEL_PROMPT
from service.clients import MLClient, ToirClient
from test_agent import ANOMALY, call, make_agent, say


@pytest.mark.parametrize("level", ["expert", "steps"])
def test_level_sets_format_and_max_tokens(ml: MLClient, toir: ToirClient, level: Any) -> None:
    steps = [call("search_manual", query="давление масла"), say("Не менее 0,1 МПа [R1].")]
    ag, llm = make_agent(steps, ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Какое давление масла?", level)
    assert llm.max_tokens and set(llm.max_tokens) == {LEVEL_MAX_TOKENS[level]}
    user = [m for m in llm.seen[0] if m["role"] == "user"][-1]["content"]
    assert LEVEL_PROMPT[level] in user and user.endswith("Какое давление масла?")
    assert all(m["role"] != "system" for m in llm.seen[0][2:]), "system — только в начале (GigaChat)"
    assert reply.notes == []  # guard тот же: 0,1 МПа есть во фрагменте


def test_expert_is_shorter_than_steps() -> None:
    assert LEVEL_MAX_TOKENS["expert"] < LEVEL_MAX_TOKENS["steps"]
    assert "Безопасность" in LEVEL_PROMPT["steps"] and "инструмент" in LEVEL_PROMPT["expert"]


def test_cache_separates_levels(ml: MLClient, toir: ToirClient) -> None:
    """Один вопрос в двух уровнях — два разных ответа: «Опытный» не получит из кэша пошаговый."""
    ag, _ = make_agent([], ml, toir)
    conv = ag.start(*ANOMALY)
    conv.messages.append({"role": "user", "content": "зазор клапанов"})
    expert = ag._answer_cache_key(conv, "зазор клапанов", "expert")
    steps = ag._answer_cache_key(conv, "зазор клапанов", "steps")
    assert expert and steps and expert != steps


def test_api_passes_level(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_api import _agent

    ag = _agent(ml, toir, [say("Коротко.")])
    monkeypatch.setattr(main, "agent", lambda: ag)
    main.limiter.cache_clear()
    vid, sid = ANOMALY
    client = TestClient(main.app)
    r = client.post("/api/chat", json={"vehicle_id": vid, "session_id": sid, "message": "?", "level": "expert"})
    assert r.status_code == 200
    assert ag.provider.max_tokens == [LEVEL_MAX_TOKENS["expert"]]
    bad = client.post("/api/chat", json={"vehicle_id": vid, "session_id": sid, "message": "?", "level": "boss"})
    assert bad.status_code == 422
