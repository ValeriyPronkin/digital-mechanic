"""Слой совместимости интерфейса v2 (#52): API Никиты поверх нашей логики — С1 целиком через /api/v2."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from service import api_v2, main
from service.clients import MLClient, ToirClient
from service.store import Store
from test_agent import ANOMALY, DRAFT, call, make_agent, say


def events(resp: Any) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in resp.text.split("\n") if line.startswith("data: ")]


@pytest.fixture
def v2(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Any, Store]:
    steps = [
        say("Давление масла на холостом ходу не менее 0,1 МПа [R1]."),  # 1-й вопрос: диагноз и поиск — код (#16)
        call("search_manual", query="давление масла"),
        call("draft_ticket", **DRAFT),
        say("Черновик заявки готов [R1]."),
    ]
    ag, _ = make_agent(steps, ml, toir)
    store = ag.store
    monkeypatch.setattr(main, "agent", lambda: ag)
    monkeypatch.setattr(main, "store", lambda: store)
    main.limiter.cache_clear()
    threads = api_v2.ThreadStore()
    app = main.FastAPI()
    app.include_router(api_v2.build_router(lambda: ag, lambda: store, main.fleet, lambda r: None, threads))
    return TestClient(app), ag, store


def test_fleet_and_vehicle(v2: tuple[TestClient, Any, Store]) -> None:
    c, _, _ = v2
    f = c.get("/api/v2/fleet").json()
    assert sum(f["counts"].values()) == len(f["vehicles"]) == 50
    assert f["vehicles"][0]["fleet"]["status"] == "quarantine"  # сначала то, чем главный механик занимается первым
    vid, _ = ANOMALY
    d = c.get(f"/api/v2/vehicles/{vid}").json()
    assert d["vehicle_id"] == vid and d["sessions"] and d["manuals"] and d["trend"]
    assert {"status", "anomaly_score", "fits_engine"} <= set(d["sessions"][0])
    dates = [x["checked_at"] for x in d["sessions"]]
    assert dates == sorted(dates)  # интерфейс v2 считает последней проверкой последний элемент списка
    assert c.get("/api/v2/vehicles/NOPE").status_code == 404


def test_c1_through_v2(v2: tuple[TestClient, Any, Store]) -> None:
    c, _, store = v2
    vid, sid = ANOMALY
    r = c.post(
        "/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Что с двигателем?", "new_thread": True}
    )
    ev = events(r)
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "thread" and kinds[-1] == "done" and "verification" in kinds
    verdict = next(e["block"] for e in ev if e["type"] == "tool_result" and e.get("block"))
    assert verdict["kind"] == "verdict" and verdict["case"] == "anomaly" and verdict["urgency"]["level"] == "high"
    text = next(e for e in ev if e["type"] == "text")["text"]
    assert "[S1]" in text and "[R1]" not in text
    src = next(e for e in ev if e["type"] == "sources")["items"][0]
    assert src["handle"] == "S1" and src["pdf_page"] == 42
    ver = next(e for e in ev if e["type"] == "verification")
    assert ver["verified"] == ["S1"] and ver["counts"]["verified"] == 1
    use = next(e for e in ev if e["type"] == "usage")
    assert use["input_tokens"] + use["cache_read_tokens"] == 1000  # кэш провайдера не считается дважды
    pp = next(e for e in ev if e["type"] == "passport")  # паспорт запроса (#31) — для «?» в v2
    assert pp["question"]["level"] == "steps" and pp["total"]["model_rub"] >= 0
    sp = next(e for e in ev if e["type"] == "speech")  # короткая озвучка (#14) — по подписи сервера
    assert "0,1 МПа" in sp["text"] and sp["url"] == "/api/voice/speak" and len(sp["sig"]) == 64

    restored = c.get(f"/api/v2/threads/current?vehicle_id={vid}").json()
    assert restored["session_id"] == sid and len(restored["transcript"]) == 2
    assert restored["transcript"][1]["passport"]["total"]["model_rub"] >= 0  # паспорт — и после перезагрузки

    r2 = c.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Создать заявку на дефектовку"})
    pending = next(e for e in events(r2) if e["type"] == "ticket_pending")
    assert pending["payload"]["urgency"] == "high" and pending["operations"][0]["text"].startswith("Замерить")

    bad = c.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid, "urgency": "low"})
    assert bad.status_code == 409 and "D-6" in bad.json()["detail"]  # приоритет — правило кода
    ok = c.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid, "keep_operations": [0]})
    view = ok.json()
    assert ok.status_code == 200 and view["ticket_id"].startswith("TKT-") and view["urgency_proposed"] == "high"
    again = c.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid})
    assert again.status_code == 409  # черновик погашен — повторно не уходит

    lst = c.get(f"/api/v2/vehicles/{vid}/tickets").json()
    assert [t["ticket_id"] for t in lst] == [view["ticket_id"]]
    out = c.post(f"/api/v2/tickets/{view['id']}/outcome", json={"outcome": "confirmed", "note": "подтвердилось"}).json()
    assert out["outcome"] == "confirmed"
    csv_text = c.get("/api/v2/outcomes.csv").text
    assert view["ticket_id"] in csv_text and "confirmed" in csv_text
    assert c.get("/api/v2/fleet").json()["outcomes"] == {"tickets": 1, "recorded": 1, "confirmed": 1}
    assert store.ticket(view["id"]) is not None


def test_thread_is_per_browser(v2: tuple[TestClient, Any, Store]) -> None:
    c, _, _ = v2
    vid, sid = ANOMALY
    c.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Что с двигателем?"})
    assert c.get(f"/api/v2/threads/current?vehicle_id={vid}").json() is not None
    stranger = TestClient(c.app)
    assert stranger.get(f"/api/v2/threads/current?vehicle_id={vid}").json() is None


def test_thread_store_survives_instance_switch() -> None:
    shared: dict[str, bytes] = {}  # один бакет на два экземпляра стенда

    class Bucket:
        objects = shared

        def get(self, key: str) -> bytes:
            return self.objects[key]

        def put(self, key: str, data: bytes, content_type: str = "") -> None:
            self.objects[key] = data

    a, b = api_v2.ThreadStore(Bucket()), api_v2.ThreadStore(Bucket())
    a.put("browser1234567890", "M333YK47", {"thread_id": "t", "session_id": "S-0005"})
    assert b.get("browser1234567890", "M333YK47") == {"thread_id": "t", "session_id": "S-0005"}


def test_transcribe_wav(ml: MLClient, toir: ToirClient) -> None:
    from test_voice import FakeSpeech, wav

    ag, _ = make_agent([], ml, toir)
    store = ag.store
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(lambda: ag, lambda: store, main.fleet, lambda r: None, api_v2.ThreadStore(), FakeSpeech)
    )
    c = TestClient(app)
    r = c.post("/api/v2/transcribe", content=wav(2.0), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 200 and r.json() == {"text": "какой тепловой зазор клапанов"}
    assert store.voice_spent_rub() > 0
    bad = c.post("/api/v2/transcribe", content=b"webm-bytes", headers={"Content-Type": "audio/webm"})
    assert bad.status_code == 422  # не WAV — понятная ошибка, а не сбой


def test_quote_line_is_the_line_with_the_number() -> None:
    page = "22 ТЕХНИЧЕСКОЕ ОБСЛУЖИВАНИЕ\nРегулировать зазор 0,25-0,30 мм на холодном двигателе.\nПрочее."
    assert api_v2.quote_line("Зазор 0,25–0,30 мм [R1].", "R1", page).startswith("Регулировать зазор")
    assert api_v2.quote_line("Без чисел [R1].", "R1", page) == "22 ТЕХНИЧЕСКОЕ ОБСЛУЖИВАНИЕ"
    # число из предложения с другой ссылкой не уводит строку этой страницы
    assert api_v2.quote_line("Момент 22 Н·м [R2]. Без чисел [R1].", "R1", page) == "22 ТЕХНИЧЕСКОЕ ОБСЛУЖИВАНИЕ"
