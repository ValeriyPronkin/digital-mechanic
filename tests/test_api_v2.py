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
    assert pp["question"]["level"] == "mechanic" and pp["question"]["level_reason"].startswith("по вопросу")
    assert pp["total"]["model_rub"] >= 0
    sp = next(e for e in ev if e["type"] == "speech")  # короткая озвучка (#14) — по подписи сервера
    assert "0,1 МПа" in sp["text"] and sp["url"] == "/api/voice/speak" and len(sp["sig"]) == 64

    restored = c.get(f"/api/v2/threads/current?vehicle_id={vid}").json()
    assert restored["session_id"] == sid and len(restored["transcript"]) == 2
    assert restored["transcript"][1]["passport"]["total"]["model_rub"] >= 0  # паспорт — и после перезагрузки
    assert restored["transcript"][1]["speech"]["url"] == "/api/voice/speak"  # «Прослушать» — и после перезагрузки

    r2 = c.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Создать заявку на дефектовку"})
    pending = next(e for e in events(r2) if e["type"] == "ticket_pending")
    assert pending["payload"]["urgency"] == "high" and pending["operations"][0]["text"].startswith("Замерить")

    # приоритет предлагает правило кода, механик может выбрать другой (#60): все три, предложенный отмечен
    choices = pending["urgency_choices"]
    assert [ch["level"] for ch in choices] == ["high", "medium", "low"]
    assert [ch["level"] for ch in choices if ch["proposed"]] == ["high"]
    ok = c.post(
        f"/api/v2/tickets/{pending['pending_id']}/approve",
        json={"vehicle_id": vid, "keep_operations": [0], "urgency": "low"},
    )
    view = ok.json()
    assert ok.status_code == 200 and view["ticket_id"].startswith("TKT-") and view["urgency_proposed"] == "high"
    assert view["payload"]["urgency"] == "low"  # в ТОиР ушёл выбор механика
    note = view["urgency_note"]
    assert "выбран механиком: «низкий»" in note and "по правилу кода — «высокий»" in note
    assert view["urgency_note"] in view["payload"]["conclusion"]  # и в заключении заявки — видно в ТОиР
    restored = c.get(f"/api/v2/threads/current?vehicle_id={vid}").json()
    rules = restored["transcript"][-2]["passport"]["rules"]  # паспорт ответа, предложившего заявку
    assert rules[-1] == f"Заявка {view['ticket_id']}. {view['urgency_note']}"
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
    # без числа из ответа строки нет: ни колонтитул с номером страницы, ни первая строка не выдаются за найденное
    assert api_v2.quote_line("Без чисел [R1].", "R1", page) == ""
    assert api_v2.quote_line("Момент 22 Н·м [R1].", "R1", page) == ""  # «22» — номер страницы в колонтитуле
    # число из предложения с другой ссылкой не уводит строку этой страницы
    assert api_v2.quote_line("Момент 22 Н·м [R2]. Без чисел [R1].", "R1", page) == ""


def test_contradiction_as_block_and_not_repeated_in_text(ml: MLClient, toir: ToirClient) -> None:
    """Противоречие руководств (D-20) — отдельный блок v2: обе формулировки дословно со страницами, вывод, совет;
    тот же блок из текста ответа убран, чтобы механик не читал его дважды."""
    from service import contradictions

    ag, _ = make_agent([], ml, toir)
    conv = ag.start(*ANOMALY)
    k = next(k for k in contradictions.known() if conv.vehicle.engine_model in k.engines)
    quotes = list(k.quotes)
    for q in quotes:
        ag._source_for(conv, q.doc, q.page, k.title, q.quote)
    conv.contradiction = (k, quotes)
    pages = {(q.doc, q.page) for q in quotes}
    refs = {(s.manual_id, s.pdf_page): s.ref for s in conv.sources.values() if (s.manual_id, s.pdf_page) in pages}
    blk = contradictions.block(
        k, quotes, refs, "Передано главному механику на решение (№ 3). Пока — безопасное правило: x."
    )
    first = blk.split("\n")[1]
    marked = blk.replace(first, first + " (испытания на стенде)")  # пометку дописывает код после вставки
    text = "Прямой ответ.\n\n" + marked + "\n\nДальше по шагам."
    block, rest = api_v2.contradiction_block(conv, text)
    assert block is not None and block["kind"] == "contradiction" and len(block["items"]) >= 2
    assert all(i["quote"] and i["handle"].startswith("S") for i in block["items"])
    assert block["items"][0]["note"] == "испытания на стенде" and block["items"][1]["note"] is None
    assert block["advice"].startswith("Передано главному механику") and block["conclusion"]
    assert block["escalation"] == {"line": block["advice"], "number": 3, "resolved": False}
    assert rest == "Прямой ответ.\n\nДальше по шагам." and contradictions.HEADER not in rest
    conv.contradiction = None
    assert api_v2.contradiction_block(conv, text) == (None, text)


def test_urgency_note_names_rule_and_choice() -> None:
    from service.api_v2 import urgency_note

    assert urgency_note("high", "high", "код F01.") == (
        "Приоритет по правилу кода — «высокий» (код F01); механик оставил его."
    )
    assert urgency_note("high", "medium", "код F01") == (
        "Приоритет выбран механиком: «средний»; по правилу кода — «высокий» (код F01)."
    )


def test_back_translation_follows_answer(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Хинди: ответ — сразу, «по-русски» (back_translation) — следом; язык и голос — событием language."""
    ag, _ = make_agent([say("मैनोमीटर से तेल का दबाव जाँचें।"), say("Проверьте давление масла манометром.")],
                       ml, toir, prefetch=False)  # fmt: skip
    app = main.FastAPI()
    app.include_router(api_v2.build_router(lambda: ag, lambda: ag.store, main.fleet, lambda r: None,
                                           api_v2.ThreadStore()))  # fmt: skip
    vid, sid = ANOMALY
    r = TestClient(app).post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "new_thread": True,
                                                   "message": "तेल का दबाव कैसे जाँचें? क्या करना चाहिए?"})  # fmt: skip
    ev = events(r)
    kinds = [e["type"] for e in ev]
    assert kinds.index("text") < kinds.index("back_translation")
    assert next(e for e in ev if e["type"] == "back_translation")["text"] == "Проверьте давление масла манометром."
    lang = next(e for e in ev if e["type"] == "language")
    assert lang["lang"] == "hi" and not lang["voice_output"]
    assert next(e for e in ev if e["type"] == "speech")["text"].startswith("Озвучки на языке «хинди» нет")
