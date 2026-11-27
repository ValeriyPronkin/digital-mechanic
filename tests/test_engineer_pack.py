"""Пакет для инженера (#40 п. 7): сбор по стенду и один HTML — группы, заявка или причина отказа, экранирование."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from engineer_pack import collect, group_of, refusal, render
from service import main
from service.clients import MLClient, ToirClient
from test_agent import make_agent, say


@pytest.fixture
def stand(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    ag, _ = make_agent([say("Проверка не удалась — повторите запись.")] * 20, ml, toir)
    monkeypatch.setattr(main, "agent", lambda: ag)
    monkeypatch.setattr(main, "ml_client", lambda: ml)
    main.limiter.cache_clear()
    return TestClient(main.app)


def test_collect_only_anomalies_and_failures(stand: TestClient) -> None:
    rows = collect(stand, "", limit=4, pause=0)
    assert len(rows) == 4
    assert all(r["card"]["status"] in ("anomaly", "check_failed") for r in rows)
    assert all("passport" in r["answer"] for r in rows)


def _row(card: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    return {
        "vehicle": {"vehicle_id": "H142OX78", "engine_model": "ЯМЗ-236М2"},
        "session": {"session_id": "S-0113"},
        "card": card,
        "question": "Что с двигателем?",
        "answer": answer,
    }


def test_render_groups_escapes_and_explains_refusal() -> None:
    failed = {
        "status": "check_failed", "title": "Проверка не удалась", "action": "Повторите запись.", "banners": [],
        "ticket_possible": False, "confidence_pct": None, "ml_quote": "Запись отбракована. <script>x</script>",
        "ml_injection": "<script>x</script>",
    }  # fmt: skip
    noisy = {
        **failed,
        "status": "anomaly",
        "title": "Неисправность",
        "ticket_possible": True,
        "danger_class": 3,
        "banners": ["Запись с помехами, уверенность снижена"],
        "ml_injection": None,
        "ml_quote": "Стук",
    }
    answer = {"text": "Повторите запись.", "notes": [], "sources": [], "trace": {"tokens_in": 10, "tokens_out": 2},
              "passport": {"tools": [{"tool": "draft_ticket", "refused": "Проверка не удалась"}],
                           "total": {"model_rub": 0.01, "total_rub": 0.01}}}  # fmt: skip
    assert group_of(failed) == "check_failed" and group_of(noisy) == "noisy"
    assert refusal(answer, failed) == "Проверка не удалась"
    page = render([_row(failed, answer), _row(noisy, {**answer, "passport": {}})], "https://stand/", datetime.now())
    assert "<script>x</script>" not in page and "&lt;script&gt;" in page
    assert "Посторонний текст (отложен, не выполнен)" in page
    assert 'id="g-noisy"' in page and 'id="g-check_failed"' in page and "Заявки нет:" in page


class _Flaky:
    """Стенд, который отвечает 502 / рвёт связь на заданные запросы, остальное — настоящему приложению."""

    def __init__(self, app: TestClient, fail: dict[str, int]) -> None:
        self.app, self.fail = app, fail

    def _hit(self, url: str, body: Any) -> Any:
        key = (body or {}).get("session_id") if url.endswith("/api/diagnose") else None
        left = self.fail.get(key or "", 0)
        if left:
            self.fail[str(key)] = left - 1
            if left % 2:
                raise httpx.ConnectError("EOF occurred in violation of protocol")
            return httpx.Response(502)
        return None

    def post(self, url: str, json: Any = None) -> Any:
        return self._hit(url, json) or self.app.post(url, json=json)

    def get(self, url: str) -> Any:
        return self.app.get(url)


def test_collect_retries_and_marks_what_the_stand_did_not_give(stand: TestClient) -> None:
    first = collect(stand, "", limit=2, pause=0)
    a, b = (r["session"]["session_id"] for r in first)
    skipped: list[dict[str, Any]] = []
    flaky = _Flaky(stand, {a: 2, b: 99})  # a: обрыв и 502, затем ответ; b: не отвечает никогда
    rows = collect(flaky, "", pause=0, only={a, b}, skipped=skipped, backoff=0)  # type: ignore[arg-type]
    assert [r["session"]["session_id"] for r in rows] == [a]
    assert [k["session"]["session_id"] for k in skipped] == [b] and "после 6 попыток" in skipped[0]["reason"]
    page = render(rows, "https://stand/", datetime.now(), skipped)
    assert "Не получены со стенда (1)" in page and f"--only {b}" in page
