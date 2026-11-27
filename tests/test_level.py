"""Уровень механика (#17; встреча 27.11): три уровня, по вопросу на каждый вопрос заново; правила кода — те же."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from service import main
from service.agent import LEVEL_MAX_TOKENS, LEVEL_PROMPT, LEVELS, resolve_level
from service.clients import MLClient, ToirClient
from test_agent import ANOMALY, call, make_agent, say


@pytest.mark.parametrize("level", LEVELS)
def test_level_sets_format_and_max_tokens(ml: MLClient, toir: ToirClient, level: Any) -> None:
    steps = [call("search_manual", query="давление масла"), say("Не менее 0,1 МПа [R1].")]
    ag, llm = make_agent(steps, ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Какое давление масла?", level)
    assert llm.max_tokens and set(llm.max_tokens) == {LEVEL_MAX_TOKENS[level]}
    user = [m for m in llm.seen[0] if m["role"] == "user"][-1]["content"]
    assert LEVEL_PROMPT[level] in user and user.endswith("Какое давление масла?")
    assert all(m["role"] != "system" for m in llm.seen[0][2:]), "system — только в начале (GigaChat)"
    assert reply.notes == []  # guard тот же: 0,1 МПа есть во фрагменте
    assert reply.level_used == level and reply.level_reason == "выбран механиком"


def test_levels_differ_in_length_and_content() -> None:
    assert LEVEL_MAX_TOKENS["master"] < LEVEL_MAX_TOKENS["mechanic"] < LEVEL_MAX_TOKENS["novice"]
    novice = LEVEL_PROMPT["novice"]
    assert "Безопасность" in novice and "Понадобится" in novice and "проверить результат" in novice
    assert "только прямой ответ" in LEVEL_PROMPT["master"] and "[R…]" in LEVEL_PROMPT["master"]


@pytest.mark.parametrize(
    ("question", "level"),
    [
        ("Как отрегулировать тепловой зазор клапанов?", "novice"),
        ("Что такое форсунка?", "novice"),
        ("Чем проверить давление масла?", "novice"),
        ("Можно ли ехать своим ходом на базу?", "novice"),
        ("Зазор клапанов?", "master"),
        ("Момент затяжки головки", "master"),
        ("Какое давление масла на холостом ходу?", "master"),
        ("Сколько масла в картере", "master"),
        ("Стук в двигателе при прогреве после замены масла, что проверить в первую очередь", "mechanic"),
        ("Посмотри результат диагностики", "mechanic"),
    ],
)
def test_level_by_question(question: str, level: str) -> None:
    used, why = resolve_level(question, "auto")
    assert used == level and why.startswith("по вопросу")


def test_choice_and_legacy_levels() -> None:
    assert resolve_level("Как снять форсунку?", "master") == ("master", "выбран механиком")  # переключил механик
    assert resolve_level("Зазор?", "steps")[0] == "novice"  # «Пошагово»
    assert resolve_level("Как снять форсунку?", "expert")[0] == "master"  # «Опытный»
    assert resolve_level("Зазор?", None)[0] == "master"  # не указан — по вопросу


def test_level_is_per_question_not_remembered(ml: MLClient, toir: ToirClient) -> None:
    """Уровень не запоминается за механиком: следующий вопрос в той же нити — снова по вопросу."""
    steps = [say("Не менее 0,1 МПа [R1]."), say("Шаги.")]
    ag, llm = make_agent([call("search_manual", query="давление масла"), *steps], ml, toir)
    conv = ag.start(*ANOMALY)
    first = ag.ask(conv, "Давление масла?", "novice")
    second = ag.ask(conv, "Давление масла?")
    assert first.level_used == "novice" and second.level_used == "master"
    assert llm.max_tokens[-1] == LEVEL_MAX_TOKENS["master"]


def test_cache_separates_levels(ml: MLClient, toir: ToirClient) -> None:
    """Один вопрос на разных уровнях — разные ответы: «Мастер» не получит из кэша пошаговый."""
    ag, _ = make_agent([], ml, toir)
    conv = ag.start(*ANOMALY)
    conv.messages.append({"role": "user", "content": "зазор клапанов"})
    keys = {ag._answer_cache_key(conv, "зазор клапанов", lv) for lv in LEVELS}
    assert None not in keys and len(keys) == 3


def test_api_passes_level(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_api import _agent

    ag = _agent(ml, toir, [say("Коротко."), say("Коротко.")])
    monkeypatch.setattr(main, "agent", lambda: ag)
    main.limiter.cache_clear()
    vid, sid = ANOMALY
    client = TestClient(main.app)
    r = client.post("/api/chat", json={"vehicle_id": vid, "session_id": sid, "message": "?", "level": "expert"})
    assert r.status_code == 200 and r.json()["level_used"] == "master"
    assert ag.provider.max_tokens == [LEVEL_MAX_TOKENS["master"]]
    r = client.post("/api/chat", json={"vehicle_id": vid, "session_id": sid, "message": "?", "level": "mechanic"})
    assert r.json()["level_used"] == "mechanic" and r.json()["level_reason"] == "выбран механиком"
    bad = client.post("/api/chat", json={"vehicle_id": vid, "session_id": sid, "message": "?", "level": "boss"})
    assert bad.status_code == 422


def test_v2_chat_reports_level(ml: MLClient, toir: ToirClient) -> None:
    import json

    from service import api_v2

    ag, _ = make_agent([say("Не менее 0,1 МПа [R1]."), say("Порядок.")], ml, toir)
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore())
    )
    c = TestClient(app)
    vid, sid = ANOMALY
    r = c.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Как проверить давление масла?"})
    text = next(json.loads(x[6:]) for x in r.text.split("\n") if x.startswith("data: ") and '"type": "text"' in x)
    assert text["level_used"] == "novice" and text["level_word"] == "Новичок" and text["level_reason"]
    restored = c.get(f"/api/v2/threads/current?vehicle_id={vid}").json()
    assert restored["transcript"][-1]["level_used"] == "novice"  # и после перезагрузки


def test_cache_key_changes_with_level_prompt(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Правка текста уровня не должна отдавать из кэша ответ в старом формате."""
    from service import agent as agent_mod

    ag, _ = make_agent([], ml, toir)
    conv = ag.start(*ANOMALY)
    conv.messages.append({"role": "user", "content": "зазор клапанов"})
    before = ag._answer_cache_key(conv, "зазор клапанов", "novice")
    monkeypatch.setitem(agent_mod.LEVEL_PROMPT, "novice", agent_mod.LEVEL_PROMPT["novice"] + " Новое правило.")
    assert ag._answer_cache_key(conv, "зазор клапанов", "novice") != before


def test_sources_carry_quote_for_as_in_manual(ml: MLClient, toir: ToirClient) -> None:
    """«Как в руководстве» (#17): у источника — дословный фрагмент; картинки нет, если нет PDF на сервере."""
    steps = [call("search_manual", query="давление масла"), say("Не менее 0,1 МПа [R1].")]
    ag, _ = make_agent(steps, ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Какое давление масла?")
    src = reply.sources[0]
    assert "0,1 МПа" in src["quote"] and src["image"] is None  # doc-1 — тестовый, PDF нет


def test_page_image_404_without_pdf() -> None:
    client = TestClient(main.app)
    assert client.get("/manuals/doc-1/page/1.png").status_code == 404


def test_page_image_renders_real_page() -> None:
    from service.manual_search import manual_pdf

    if manual_pdf("yamz-236-rk") is None:
        pytest.skip("нужны PDF руководств (MANUALS_DIR)")
    client = TestClient(main.app)
    r = client.get("/manuals/yamz-236-rk/page/270.png")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/manuals/yamz-236-rk/page/99999.png").status_code == 404
