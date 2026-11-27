"""Карточка проверки в /api/v2/chat — до первого вызова модели (замер 27.11): она из полей ML и правил кода,
приходит первой и остаётся у механика, если модель упала или кончился лимит расходов."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from service import api_v2, main
from service.agent import Agent
from service.clients import MLClient, ToirClient
from service.llm import LLMError, LLMReply
from test_agent import ANOMALY, FAILED, make_agent, say


def client(ag: Agent) -> TestClient:
    app = main.FastAPI()
    threads = api_v2.ThreadStore()
    app.include_router(api_v2.build_router(lambda: ag, lambda: ag.store, main.fleet, lambda r: None, threads))
    return TestClient(app)


def chat(c: TestClient, message: str) -> list[dict[str, Any]]:
    vid, sid = ANOMALY
    r = c.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": message})
    assert r.status_code == 200
    return [json.loads(line[6:]) for line in r.text.split("\n") if line.startswith("data: ")]


def verdicts(ev: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in ev if e["type"] == "tool_result" and (e.get("block") or {}).get("kind") == "verdict"]


def test_card_is_sent_before_the_first_model_call(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    sse = api_v2._sse

    def logged(event: dict[str, Any]) -> str:
        kind = (event.get("block") or {}).get("kind") if event["type"] == "tool_result" else None
        order.append(f"{event['type']}:{kind}" if kind else event["type"])
        return sse(event)

    def model(_: Any) -> LLMReply:
        order.append("model")
        return say("Ответ.")

    monkeypatch.setattr(api_v2, "_sse", logged)
    ag, _ = make_agent([model], ml, toir)
    ev = chat(client(ag), "Что с двигателем?")
    assert order.index("tool_result:verdict") < order.index("model")
    assert len(verdicts(ev)) == 1  # одна карточка, а не две
    started = [e for e in ev if e["type"] == "tool_started" and e["name"] == "get_diagnosis"]
    assert len(started) == 1  # и одна строка «Результат проверки» в журнале действий
    assert [e["type"] for e in ev][-1] == "done"


@pytest.mark.parametrize("failure", ["model", "budget"])
def test_card_stays_when_the_model_fails(ml: MLClient, toir: ToirClient, failure: str) -> None:
    def down(_: Any) -> LLMReply:
        raise LLMError("Модель не ответила.")

    if failure == "model":
        ag, _ = make_agent([down], ml, toir)
    else:  # лимит на сегодня исчерпан: модель не вызывается вовсе
        ag, _ = make_agent([], ml, toir, budget_day_rub=0.0)
    c = client(ag)
    ev = chat(c, "Что с двигателем?")
    types = [e["type"] for e in ev]
    assert types[-2:] == ["error", "done"] and ev[-1]["reason"] == "error"
    card = verdicts(ev)
    assert len(card) == 1 and types.index("tool_result") < types.index("error")
    assert card[0]["block"]["fault_code"] == "F02" and card[0]["block"]["status"] == "anomaly"
    saved = c.get(f"/api/v2/threads/current?vehicle_id={ANOMALY[0]}").json()  # и после перезагрузки страницы
    assert saved["transcript"][0] == {"role": "user", "text": "Что с двигателем?"}
    assert saved["transcript"][1]["blocks"][0]["kind"] == "verdict"


def test_card_is_sent_once_per_thread(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Ответ 1."), say("Ответ 2.")], ml, toir)
    c = client(ag)
    assert len(verdicts(chat(c, "Что с двигателем?"))) == 1
    assert verdicts(chat(c, "А что проверить?")) == []
    saved = c.get(f"/api/v2/threads/current?vehicle_id={ANOMALY[0]}").json()
    blocks = [b["kind"] for t in saved["transcript"] if t["role"] == "assistant" for b in t["blocks"]]
    assert blocks.count("verdict") == 1


def test_card_alone_by_get_without_the_model(ml: MLClient, toir: ToirClient) -> None:
    """Отдельный запрос карточки: те же поля, что в потоке чата, и ни одного вызова модели."""
    ag, llm_ = make_agent([say("Ответ.")], ml, toir)
    c = client(ag)
    vid, sid = ANOMALY
    r = c.get(f"/api/v2/vehicles/{vid}/verdict", params={"session_id": sid})
    assert r.status_code == 200 and llm_.seen == []
    assert r.json() == verdicts(chat(c, "Что с двигателем?"))[0]["block"]
    assert c.get(f"/api/v2/vehicles/{vid}/verdict", params={"session_id": "S-9999"}).status_code == 404
    assert c.get("/api/v2/vehicles/NOPE/verdict", params={"session_id": sid}).status_code == 404


def test_failed_check_card_by_get(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([], ml, toir)
    r = client(ag).get(f"/api/v2/vehicles/{FAILED[0]}/verdict", params={"session_id": FAILED[1]})
    assert r.status_code == 200 and r.json()["case"] == "failed" and r.json()["fault_code"] is None
