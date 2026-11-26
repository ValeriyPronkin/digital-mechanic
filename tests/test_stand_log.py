"""Журнал стенда в бакете (issue #27): белый список полей, пачки, сутки по Москве, сбой бакета, сводка."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from service import main
from service.spend import MSK
from service.stand_log import BATCH, StandLog

TS = datetime(2026, 11, 28, 12, 0, tzinfo=MSK).timestamp()


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.down = False

    def put(self, key: str, data: bytes) -> None:
        if self.down:
            raise ConnectionError("бакет недоступен")
        self.objects[key] = data

    def lines(self, key: str) -> list[dict[str, object]]:
        return [json.loads(x) for x in self.objects[key].decode().splitlines()]


def _log(bucket: FakeBucket, now: list[float]) -> StandLog:
    return StandLog(bucket.put, instance="inst1", clock=lambda: now[0])


def test_only_whitelisted_fields_reach_the_log() -> None:
    b, now = FakeBucket(), [TS]
    slog = _log(b, now)
    slog.event("request", route="/api/chat", method="POST", status=200, ms=812,
               message="Механик Иванов: какой зазор?", vehicle_id="A464EP47")  # fmt: skip
    slog.flush()
    (rec,) = b.lines("logs/2026-11-28/inst1.jsonl")
    assert rec["route"] == "/api/chat" and rec["ms"] == 812 and rec["instance"] == "inst1"
    raw = b.objects["logs/2026-11-28/inst1.jsonl"].decode()
    assert "Иванов" not in raw and "A464EP47" not in raw and "зазор" not in raw


def test_batch_flush_and_whole_day_file() -> None:
    b, now = FakeBucket(), [TS]
    slog = _log(b, now)
    for i in range(BATCH):
        slog.event("step", step="model", ms=i)
    assert len(b.lines("logs/2026-11-28/inst1.jsonl")) == BATCH  # пачка ушла сама
    slog.event("step", step="search", ms=5)
    slog.flush()
    assert len(b.lines("logs/2026-11-28/inst1.jsonl")) == BATCH + 1  # файл суток перезаписан целиком


def test_day_change_flushes_previous_day() -> None:
    b, now = FakeBucket(), [datetime(2026, 11, 28, 23, 59, tzinfo=MSK).timestamp()]
    slog = _log(b, now)
    slog.event("step", step="model", ms=1)
    now[0] = datetime(2026, 11, 29, 0, 1, tzinfo=MSK).timestamp()
    slog.event("step", step="model", ms=2)
    slog.flush()
    assert len(b.lines("logs/2026-11-28/inst1.jsonl")) == 1 and len(b.lines("logs/2026-11-29/inst1.jsonl")) == 1


def test_bucket_failure_keeps_events() -> None:
    b, now = FakeBucket(), [TS]
    slog = _log(b, now)
    b.down = True
    slog.event("error", error="LLMError", route="/api/chat", status=502)
    assert slog.flush() is False  # сервис не падает
    b.down = False
    slog.event("step", step="model", ms=3)
    assert slog.flush() is True
    assert [r["kind"] for r in b.lines("logs/2026-11-28/inst1.jsonl")] == ["error", "step"]


def test_middleware_logs_route_template_not_values(monkeypatch: pytest.MonkeyPatch) -> None:
    b, now = FakeBucket(), [TS]
    slog = _log(b, now)
    monkeypatch.setattr(main, "journal", lambda: slog)
    client = TestClient(main.app)
    assert client.get("/api/vehicles/A464EP47").status_code == 200
    client.get("/api/vehicles/NOPE")
    client.get("/health")  # проба здоровья журнал не засоряет
    slog.flush()
    recs = b.lines("logs/2026-11-28/inst1.jsonl")
    route = "/api/vehicles/{vehicle_id}"
    assert [(r["route"], r["status"]) for r in recs] == [(route, 200), (route, 404)]
    assert "A464EP47" not in b.objects["logs/2026-11-28/inst1.jsonl"].decode()


def test_chat_steps_are_named_without_text() -> None:
    b, now = FakeBucket(), [TS]
    slog = _log(b, now)
    original = main.journal
    main.journal = lambda: slog  # type: ignore[assignment]
    try:
        main.log_steps({"steps": [
            {"kind": "llm", "name": "deepseek-flash (план поиска)", "ms": 900},
            {"kind": "tool", "name": "get_diagnosis (код)", "ms": 40, "ok": True},
            {"kind": "tool", "name": "search_manual (код)", "ms": 120, "ok": True},
            {"kind": "llm", "name": "deepseek-flash", "ms": 2100},
        ]})  # fmt: skip
    finally:
        main.journal = original  # type: ignore[assignment]
    slog.flush()
    assert [r["step"] for r in b.lines("logs/2026-11-28/inst1.jsonl")] == ["plan", "diagnose", "search", "model"]


def test_summary_counts_and_percentiles() -> None:
    from stand_logs import render, summarize

    events = [
        {"kind": "start", "instance": "a"},
        {"kind": "start", "instance": "b"},
        *[
            {"kind": "request", "route": "/api/chat", "method": "POST", "status": 200, "ms": ms}
            for ms in range(100, 1100, 100)
        ],
        {"kind": "request", "route": "/api/chat", "method": "POST", "status": 502, "ms": 30000},
        {"kind": "step", "step": "model", "ms": 2000, "instance": "a"},
        {"kind": "step", "step": "uptime", "uptime_s": 3600, "instance": "a"},
        {"kind": "error", "error": "LLMError", "route": "/api/chat", "method": "POST"},
    ]
    s = summarize(events)
    chat = s["routes"]["POST /api/chat"]
    assert (s["instances"], s["starts"], s["max_uptime_s"]) == (2, 2, 3600)
    assert chat["count"] == 11 and chat["5xx"] == 1 and chat["p50"] == 600 and chat["p95"] == 30000
    assert s["errors"] == {"LLMError · POST /api/chat": 1}
    assert "| POST /api/chat | 11 | 1 |" in render("28.11", s)


def test_sigv4_signs_query_for_listing() -> None:
    from service.kb_store import _canonical_query, sigv4_auth

    assert _canonical_query("") == ""
    assert _canonical_query("prefix=logs/2026-11-28/&list-type=2") == "list-type=2&prefix=logs%2F2026-11-28%2F"
    fixed = datetime(2026, 11, 28, 9, 0, tzinfo=MSK)
    sign = sigv4_auth("id", "secret", now=lambda: fixed)
    a = sign("GET", "https://s3/b?list-type=2&prefix=logs/", {}, "e3b0")["authorization"]
    b = sign("GET", "https://s3/b?list-type=2&prefix=index/", {}, "e3b0")["authorization"]
    assert a != b  # параметры входят в подпись
