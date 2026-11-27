"""Отправленные заявки — общие для экземпляров стенда (аудит 27.11, A2): у каждого экземпляра своя SQLite, а список
заявок, карточка, реестр и «заявка создана» в парке должны показывать то, что отправлено через любой из них."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from service import api_v2, main
from service.clients import MLClient, ToirClient
from service.store import Store
from service.ticket_book import KEY, SharedTickets
from test_agent import ANOMALY, DRAFT, call, make_agent, say
from test_ticket_once import FakeBucket

STEPS = [
    say("Давление масла на холостом ходу не менее 0,1 МПа [R1]."),
    call("search_manual", query="давление масла"),
    call("draft_ticket", **DRAFT),
    say("Черновик заявки готов [R1]."),
]


def events(resp: Any) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in resp.text.split("\n") if line.startswith("data: ")]


def instance(ml: MLClient, toir: ToirClient, bucket: FakeBucket | None) -> TestClient:
    """Экземпляр стенда: своя SQLite, свои нити; общий у экземпляров — только бакет."""
    shared = SharedTickets(bucket.obj(KEY), sleep=lambda s: None) if bucket else None
    ag, _ = make_agent(list(STEPS), ml, toir)
    ag.store = store = Store(":memory:", shared=shared)
    app = main.FastAPI()
    app.include_router(api_v2.build_router(lambda: ag, lambda: store, main.fleet, lambda r: None, api_v2.ThreadStore()))
    return TestClient(app)


LATEST = ("B418HK98", "S-0009")  # последняя проверка машины — отклонение (по ней снимается видео)


def send(c: TestClient, check: tuple[str, str] = LATEST) -> dict[str, Any]:
    vid, sid = check
    c.post(
        "/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Что с двигателем?", "new_thread": True}
    )
    r = c.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Создать заявку на дефектовку"})
    pending = next(e for e in events(r) if e["type"] == "ticket_pending")
    view: dict[str, Any] = c.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid}).json()
    return view


def badges(c: TestClient, vid: str) -> list[dict[str, str]]:
    row = next(v for v in c.get("/api/v2/fleet").json()["vehicles"] if v["vehicle_id"] == vid)
    out: list[dict[str, str]] = row["fleet"]["badges"]
    assert c.get(f"/api/v2/vehicles/{vid}").json()["fleet"]["badges"] == out  # экран машины — то же
    return out


@pytest.fixture(autouse=True)
def _limits() -> None:
    main.limiter.cache_clear()


def test_a_ticket_sent_through_one_instance_is_seen_by_the_other(ml: MLClient, toir: ToirClient) -> None:
    bucket = FakeBucket()
    a, b = instance(ml, toir, bucket), instance(ml, toir, bucket)
    vid, _ = LATEST
    assert b.get("/api/v2/tickets").json() == [] and badges(b, vid) == []

    view = send(a)
    [row] = b.get("/api/v2/tickets").json()  # реестр главного механика на другом экземпляре
    assert (row["id"], row["ticket_id"], row["payload"]) == (view["id"], view["ticket_id"], view["payload"])
    assert row["lines"] == view["lines"] and row["lines"]["operations"]
    assert row["urgency_proposed"] == "high"
    assert [t["ticket_id"] for t in b.get(f"/api/v2/vehicles/{vid}/tickets").json()] == [view["ticket_id"]]
    assert badges(b, vid) == [{"code": "ticket_created", "label": "заявка создана"}]

    # исход дефектовки отмечен на другом экземпляре — виден на первом, в парке и в выгрузке
    out = b.post(f"/api/v2/tickets/{view['id']}/outcome", json={"outcome": "confirmed", "note": "зазор"}).json()
    assert (out["outcome"], out["outcome_note"]) == ("confirmed", "зазор")
    assert a.get(f"/api/v2/vehicles/{vid}/tickets").json()[0]["outcome"] == "confirmed"
    assert badges(a, vid) == [{"code": "ticket_created", "label": "дефектовка: подтвердилось"}]
    assert a.get("/api/v2/fleet").json()["outcomes"] == {"tickets": 1, "recorded": 1, "confirmed": 1}
    assert view["ticket_id"] in a.get("/api/v2/outcomes.csv").text


def test_without_a_bucket_and_when_it_fails_the_instance_keeps_its_own(ml: MLClient, toir: ToirClient) -> None:
    local = instance(ml, toir, None)
    vid, _ = LATEST
    view = send(local)
    assert [t["ticket_id"] for t in local.get("/api/v2/tickets").json()] == [view["ticket_id"]]
    assert badges(local, vid) == [{"code": "ticket_created", "label": "заявка создана"}]

    class Down(FakeBucket):
        def obj(self, key: str) -> Any:
            class Obj:
                def read(self) -> Any:
                    raise ConnectionError("бакет недоступен")

                def write(self, data: bytes, if_match: str | None) -> int:
                    raise ConnectionError("бакет недоступен")

            return Obj()

    broken = instance(ml, toir, Down())
    view = send(broken)  # заявка уходит, запись — у экземпляра
    assert [t["ticket_id"] for t in broken.get("/api/v2/tickets").json()] == [view["ticket_id"]]


def test_conflicting_writes_are_retried_and_a_ticket_is_kept_once() -> None:
    bucket = FakeBucket()
    one, two = (SharedTickets(bucket.obj(KEY), sleep=lambda s: None) for _ in range(2))
    row = {"id": 7, "ticket_id": "TKT-7", "vehicle_id": "A", "session_id": "S", "ts": 1.0}
    one.add(row)
    two.add(dict(row))  # та же заявка от второго экземпляра — не дублируется
    obj = bucket.obj(KEY)
    real_write = obj.write
    calls = {"n": 0}

    def racing_write(data: bytes, if_match: str | None) -> int:
        calls["n"] += 1
        if calls["n"] == 1:  # другой экземпляр успел записать между чтением и записью
            bucket.put(KEY, bucket.get(KEY))
        return real_write(data, if_match)

    obj.write = racing_write  # type: ignore[method-assign]
    SharedTickets(obj, sleep=lambda s: None).update(lambda r: r["id"] == 7, outcome="confirmed")
    assert calls["n"] == 2
    assert [(r["id"], r.get("outcome")) for r in one.all()] == [(7, "confirmed")]


def test_a_ticket_for_an_older_check_gives_no_badge(ml: MLClient, toir: ToirClient) -> None:
    c = instance(ml, toir, FakeBucket())
    vid, sid = ANOMALY
    v = main.fleet().vehicle(vid)
    assert v is not None and max(v.sessions, key=lambda s: s.checked_at).session_id != sid
    send(c, ANOMALY)
    assert badges(c, vid) == []
