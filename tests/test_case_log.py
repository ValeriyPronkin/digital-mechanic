"""Долгая сессия и запись для рекламации: история обращений, продолжение нити, запись только добавлением, выгрузка."""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from service import api_v2, main
from service.case_log import BucketBackend, CaseLog, MemoryBackend, record_hash, verify
from service.clients import MLClient, ToirClient
from test_agent import ANOMALY, DRAFT, call, make_agent, say


def test_append_only_chain_and_tamper_detection() -> None:
    log = CaseLog()
    for i in range(3):
        log.append("V1", "t1", {"kind": "answer", "question": f"q{i}"})
    recs = log.records("V1", "t1")
    assert [r["seq"] for r in recs] == [1, 2, 3] and verify(recs) == (True, "цепочка цела: записей 3")
    assert recs[1]["prev_sha256"] == recs[0]["sha256"] and recs[0]["sha256"] == record_hash(recs[0])
    key = "v2/records/V1/t1/000002.json"
    assert not log.backend.create(key, b"{}")  # существующую запись не перезаписать
    bad = [dict(r) for r in recs]
    bad[1]["answer"] = "исправлено задним числом"
    assert verify(bad)[0] is False and "изменена" in verify(bad)[1]
    assert verify([recs[0], recs[2]])[0] is False  # пропуск


def test_concurrent_appends_never_overwrite() -> None:
    backend = MemoryBackend()
    a, b = CaseLog(backend), CaseLog(backend)  # два экземпляра стенда, один бакет
    workers = [threading.Thread(target=lg.append, args=("V1", "t1", {"q": i})) for i, lg in enumerate([a, b] * 5)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    recs = a.records("V1", "t1")
    assert len(recs) == 10 and verify(recs)[0]
    assert a.thread_row("V1", "t1")["records"] == 10  # type: ignore[index]


def test_retention_hides_old_threads() -> None:
    now = [1_800_000_000.0]
    log = CaseLog(retention_days=30, clock=lambda: now[0])
    log.touch("V1", "t1", topic="стук")
    assert [r["thread_id"] for r in log.threads("V1")] == ["t1"]
    now[0] += 31 * 86400
    assert log.threads("V1") == [] and log.thread_row("V1", "t1") is None


def test_bucket_backend_maps_conditional_write() -> None:
    assert BucketBackend._status(200) and BucketBackend._status(201)
    assert BucketBackend._status(412) is False and BucketBackend._status(409) is False
    with pytest.raises(RuntimeError):
        BucketBackend._status(503)


def _events(r: Any) -> list[dict[str, Any]]:
    return [json.loads(x[6:]) for x in r.text.split("\n") if x.startswith("data: ")]


def test_long_session_through_v2(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_SHA", "0123456789abcdef0123456789abcdef01234567")
    steps = [
        say("Давление масла на холостом ходу не менее 0,1 МПа [R1]."),
        call("search_manual", query="давление масла"),
        call("draft_ticket", **DRAFT),
        say("Черновик заявки готов [R1]."),
        say("Продолжаем: давление проверено [R1]."),
    ]
    ag, _ = make_agent(steps, ml, toir)
    cases = CaseLog()
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(
            lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore(), case_log=cases
        )
    )
    phone = TestClient(app)
    vid, sid = ANOMALY
    r1 = phone.post(
        "/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Что с двигателем? 89161234567"}
    )
    tid = next(e for e in _events(r1) if e["type"] == "thread")["thread_id"]
    r2 = phone.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Создать заявку"})
    pending = next(e for e in _events(r2) if e["type"] == "ticket_pending")
    ok = phone.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid}).json()

    rows = phone.get(f"/api/v2/vehicles/{vid}/threads").json()
    assert len(rows) == 1 and rows[0]["thread_id"] == tid and rows[0]["session_id"] == sid
    assert rows[0]["topic"].startswith("Что с двигателем?") and "89161234567" not in rows[0]["topic"]  # без ПДн
    assert rows[0]["status"] == "ticket_sent" and rows[0]["ticket_id"] == ok["ticket_id"] and rows[0]["records"] == 3

    exp = phone.get(f"/api/v2/vehicles/{vid}/threads/{tid}/export").json()
    assert exp["integrity"] == {"ok": True, "detail": "цепочка цела: записей 3"}
    first, _, ticket = exp["records"]
    assert first["kind"] == "answer" and "[телефон]" in first["question"] and "0,1 МПа" in first["answer"]
    assert first["pages"][0]["handle"] == "S1" and first["pages"][0]["pdf_page"] == 42 and first["pages"][0]["quote"]
    assert first["models"] and first["provider"] and first["commit"].startswith("0123456") and "index_version" in first
    assert first["verdict"]["status"] == "anomaly" and first["at"]
    assert ticket["kind"] == "ticket" and ticket["ticket_id"] == ok["ticket_id"]
    page = phone.get(f"/api/v2/vehicles/{vid}/threads/{tid}/export?format=html").text
    assert "Целостность записи:</b> ✓" in page and ok["ticket_id"] in page and "<script" not in page

    # через полгода, с другого телефона: продолжить ту же нить
    other = TestClient(app)
    assert other.get(f"/api/v2/threads/current?vehicle_id={vid}").json() is None
    resumed = other.post(f"/api/v2/threads/{tid}/resume", json={"vehicle_id": vid}).json()
    assert resumed["thread_id"] == tid and len(resumed["transcript"]) >= 4
    r3 = other.post("/api/v2/chat", json={"vehicle_id": vid, "message": "Что дальше?"})
    assert next(e for e in _events(r3) if e["type"] == "thread")["thread_id"] == tid
    exp = other.get(f"/api/v2/vehicles/{vid}/threads/{tid}/export").json()
    assert [r["seq"] for r in exp["records"]] == [1, 2, 3, 4] and exp["integrity"]["ok"]

    # пропуск записи виден при выгрузке
    del cases.backend.objects[f"v2/records/{vid}/{tid}/000004.json"]  # type: ignore[attr-defined]
    exp = phone.get(f"/api/v2/vehicles/{vid}/threads/{tid}/export").json()
    assert exp["integrity"]["ok"] is False and "должно быть 4" in exp["integrity"]["detail"]
    assert phone.post("/api/v2/threads/nope/resume", json={"vehicle_id": vid}).status_code == 404
    assert phone.get(f"/api/v2/vehicles/{vid}/threads/nope/export").status_code == 404
