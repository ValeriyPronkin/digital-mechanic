"""Ответ доходит до механика и при сбое (ревью 27.11): ошибка инструмента — ошибка для модели, а не обрыв
потока; поток всегда заканчивается событиями error и done; у запроса общий срок; индекс, не скачанный при
старте, докачивается, а /health честно говорит, что его нет."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from service import api_v2, llm, main
from service.clients import MLClient, ToirClient
from service.llm import LLMError
from service.manual_search import EmptySearcher
from test_agent import ANOMALY, FixtureSearch, call, make_agent, say


def _tool_results(seen: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [json.loads(m["content"]) for m in seen[-1] if m["role"] == "tool"]


def test_bad_tool_argument_is_an_error_for_the_model(ml: MLClient, toir: ToirClient) -> None:
    """Повтор ревью: модель передала search_manual k="пять" — раньше ValueError обрывал весь запрос."""
    ag, llm_ = make_agent([call("search_manual", query="зазор", k="пять"), say("Ответ.")], ml, toir, prefetch=False)
    reply = ag.ask(ag.start(*ANOMALY), "Какой зазор клапанов?")
    assert reply.text.startswith("Ответ")
    assert "error" in _tool_results(llm_.seen)[-1]
    step = next(s for s in reply.trace["steps"] if s.get("tool") == "search_manual")
    assert step["ok"] is False


def test_unexpected_tool_failure_is_an_error_for_the_model(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ag, llm_ = make_agent([call("vehicle_history", vehicle_id=ANOMALY[0]), say("Ответ.")], ml, toir, prefetch=False)

    def boom(*_: Any) -> Any:
        raise KeyError("checked_at")

    monkeypatch.setattr(ag, "_vehicle_history", boom)
    reply = ag.ask(ag.start(*ANOMALY), "Что было раньше?")
    assert reply.text.startswith("Ответ") and "error" in _tool_results(llm_.seen)[-1]
    assert "checked_at" not in json.dumps(_tool_results(llm_.seen), ensure_ascii=False)  # внутренности — в журнал


def test_stream_ends_with_error_and_done_and_keeps_thread(ml: MLClient, toir: ToirClient) -> None:
    """Любое исключение в ответе: механик видит понятную ошибку, поток закрыт событием done, нить сохранена."""
    ag, _ = make_agent([], ml, toir)

    def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("сбой")

    ag.ask = broken  # type: ignore[method-assign]
    app = main.FastAPI()
    threads = api_v2.ThreadStore()
    app.include_router(api_v2.build_router(lambda: ag, lambda: ag.store, main.fleet, lambda r: None, threads))
    c = TestClient(app)
    vid, sid = ANOMALY
    r = c.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Что с двигателем?"})
    ev = [json.loads(line[6:]) for line in r.text.split("\n") if line.startswith("data: ")]
    assert r.status_code == 200 and [e["type"] for e in ev][-2:] == ["error", "done"]
    assert "сбой" not in ev[-2]["message"] and ev[-1]["reason"] == "error"
    saved = c.get(f"/api/v2/threads/current?vehicle_id={vid}").json()
    assert saved["session_id"] == sid and saved["transcript"][0] == {"role": "user", "text": "Что с двигателем?"}
    assert saved["transcript"][1]["role"] == "assistant" and saved["transcript"][1]["text"] == ev[-2]["message"]


def test_deadline_stops_the_loop_with_a_plain_note(ml: MLClient, toir: ToirClient) -> None:
    """Общий срок запроса вышел — новых вызовов модели нет, механик получает понятную строку, а не обрыв
    платформой на 120-й секунде."""
    steps = [call("search_manual", query="зазор"), say("не должен понадобиться")]
    ag, llm_ = make_agent(steps, ml, toir, prefetch=False, deadline_s=0.0)
    reply = ag.ask(ag.start(*ANOMALY), "Какой зазор клапанов?")
    assert len(llm_.seen) == 1 and reply.text == ag_note()
    assert reply.trace["deadline"] is True


def ag_note() -> str:
    from service.agent import DEADLINE_NOTE

    return DEADLINE_NOTE


def test_model_call_timeout_is_capped_by_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    class Http:
        def post(self, url: str, **kw: Any) -> httpx.Response:
            seen.append(kw.get("timeout"))
            return httpx.Response(200, json={"ok": True})

    now = 1000.0
    monkeypatch.setattr(llm.time, "monotonic", lambda: now)
    token = llm.DEADLINE.set(now + 12)
    try:
        llm._post(Http(), "/x", json={})  # type: ignore[arg-type]
        assert seen[-1].read == pytest.approx(12)
        llm.DEADLINE.set(now + 1)
        with pytest.raises(LLMError):
            llm._post(Http(), "/x", json={})  # type: ignore[arg-type]
        assert len(seen) == 1  # срок вышел — вызова нет
    finally:
        llm.DEADLINE.reset(token)


# ---------- индекс руководств ----------


def test_index_download_is_retried_with_bounds(tmp_path: Path) -> None:
    tries: list[float] = []
    clock = [0.0]
    present = [False]

    def fetch() -> bool:
        tries.append(clock[0])
        present[0] = clock[0] > 30  # бакет ожил ко второй попытке
        return present[0]

    retry = main.IndexRetry(fetch, lambda: present[0], clock=lambda: clock[0], every_s=30, max_tries=3)
    assert retry() is False and tries == [0.0]
    assert retry() is False and tries == [0.0]  # не чаще раза в 30 с
    clock[0] = 31
    assert retry() is True and tries == [0.0, 31]
    stuck = main.IndexRetry(lambda: False, lambda: False, clock=lambda: clock[0], every_s=0, max_tries=2)
    assert [stuck(), stuck(), stuck()] == [False, False, False] and stuck.tries == 2  # не больше max_tries


def test_agent_gets_the_index_once_it_is_downloaded(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ag, _ = make_agent([], ml, toir, search=EmptySearcher())
    monkeypatch.setattr(main, "_agent", lambda: ag)
    monkeypatch.setattr(main, "index_retry", lambda: True)
    monkeypatch.setattr(main, "default_searcher", lambda: FixtureSearch())
    assert isinstance(main.agent().searcher, FixtureSearch)


def test_health_is_503_while_stand_index_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "bucket")
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "none"))
    r = TestClient(main.app).get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "no_index" and body["manuals_index"]["present"] is False and body["reason"]


def test_health_ok_without_bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Локально и в CI (без S3_BUCKET) пустой индекс — не причина 503: смоук образа проходит как раньше."""
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "none"))
    assert TestClient(main.app).get("/health").status_code == 200
