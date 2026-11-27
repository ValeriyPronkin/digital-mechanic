"""Одна заявка на одно подтверждение, даже если стенд держит несколько экземпляров (ревью 27.11).

На стенде у каждого экземпляра своя SQLite (`STATE_DB=/tmp/agent.db`), а нить разговора — в общем бакете.
Защита от повтора: свежая нить из бакета при подтверждении и отметка `v2/tickets/{отпечаток}` с условной
записью (`If-None-Match: *`) до отправки в ТОиР."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from service import api_v2, conv_state, main
from service.clients import MLClient, ToirClient
from service.ticket_once import TicketMarks
from test_agent import ANOMALY, DRAFT, call, make_agent, say


class FakeBucket:
    """Общий бакет двух экземпляров: get/put для нитей и объекты с условной записью для отметок."""

    def __init__(self) -> None:
        self.d: dict[str, bytes] = {}
        self.etags: dict[str, int] = {}

    def get(self, key: str) -> bytes:
        return self.d[key]

    def put(self, key: str, data: bytes, content_type: str = "") -> None:
        self.d[key] = data
        self.etags[key] = self.etags.get(key, 0) + 1

    def obj(self, key: str) -> Any:
        bucket = self

        class Obj:
            def read(self) -> tuple[bytes | None, str | None]:
                if key not in bucket.d:
                    return None, None
                return bucket.d[key], str(bucket.etags[key])

            def write(self, data: bytes, if_match: str | None) -> int:
                exists = key in bucket.d
                if (if_match is None and exists) or (if_match is not None and str(bucket.etags.get(key)) != if_match):
                    return 412
                bucket.put(key, data)
                return 200

        return Obj()


class CountingToir(ToirClient):
    def __init__(self, inner: ToirClient) -> None:
        self.inner, self.sent = inner, 0

    def create_ticket(self, body: Any) -> Any:
        self.sent += 1
        return self.inner.create_ticket(body)


def events(resp: Any) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in resp.text.split("\n") if line.startswith("data: ")]


def _instance(ml: MLClient, toir: ToirClient, bucket: FakeBucket, steps: list[Any]) -> tuple[TestClient, Any]:
    ag, _ = make_agent(steps, ml, toir, ticket_marks=TicketMarks(bucket.obj))
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore(bucket))
    )
    return TestClient(app), ag


def _pending(client: TestClient) -> dict[str, Any]:
    vid, sid = ANOMALY
    ev = events(
        client.post(
            "/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Оформи заявку", "new_thread": True}
        )
    )
    return next(e for e in ev if e["type"] == "ticket_pending")


DRAFT_STEPS = [
    call("search_manual", query="давление масла"),
    call("draft_ticket", **DRAFT),
    say("Черновик готов [R1]."),
]


def test_second_instance_with_stale_thread_does_not_send_again(ml: MLClient, toir: ToirClient) -> None:
    """Повтор ревью: экземпляр B держал в памяти нить с черновиком; A отправил — B не отправляет второй раз."""
    bucket, counting = FakeBucket(), CountingToir(toir)
    a, _ = _instance(ml, counting, bucket, list(DRAFT_STEPS))
    b, _ = _instance(ml, counting, bucket, [])
    vid, _ = ANOMALY
    for c in (a, b):
        c.cookies.set("dm_v2", "a" * 32)  # один браузер, запросы — на разные экземпляры
    pending = _pending(a)
    assert b.get(f"/api/v2/threads/current?vehicle_id={vid}").json()["pending"]  # B запомнил нить
    r1 = a.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid})
    r2 = b.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid})
    assert r1.status_code == 200 and r2.status_code == 409
    assert counting.sent == 1


def test_simultaneous_approvals_send_one_ticket(ml: MLClient, toir: ToirClient) -> None:
    """Два экземпляра подтверждают один черновик одновременно (оба уже прочитали нить): в ТОиР — одна заявка,
    второй получает её номер."""
    bucket, counting = FakeBucket(), CountingToir(toir)
    a, _ = make_agent(list(DRAFT_STEPS), ml, counting, ticket_marks=TicketMarks(bucket.obj))
    b, _ = make_agent([], ml, counting, ticket_marks=TicketMarks(bucket.obj))
    conv = a.start(*ANOMALY)
    a.ask(conv, "Оформи заявку")
    state = conv_state.dump(conv)
    conv_a, conv_b = conv_state.load(state, a.fleet), conv_state.load(state, b.fleet)
    assert conv_a is not None and conv_b is not None and conv_a.draft is not None
    first = a.confirm_ticket(conv_a, conv_a.draft.fingerprint)
    second = b.confirm_ticket(conv_b, conv_b.draft.fingerprint)  # type: ignore[union-attr]
    assert second.ticket_id == first.ticket_id and counting.sent == 1
    assert b.store.ticket_for(fingerprint_of(state)) == first.ticket_id  # и B знает заявку (история машины)


def test_failed_send_releases_mark(ml: MLClient, toir: ToirClient) -> None:
    """ТОиР не ответил — отметка снята: механик может нажать «Отправить» снова."""
    from service.clients import ServiceError

    class DownToir(ToirClient):
        def create_ticket(self, body: Any) -> Any:
            raise ServiceError("ТОиР недоступен.")

    bucket = FakeBucket()
    ag, _ = make_agent(list(DRAFT_STEPS), ml, DownToir(), ticket_marks=TicketMarks(bucket.obj))
    conv = ag.start(*ANOMALY)
    ag.ask(conv, "Оформи заявку")
    assert conv.draft is not None
    fp = conv.draft.fingerprint
    try:
        ag.confirm_ticket(conv, fp)
    except ServiceError:
        pass
    ag.toir = toir
    assert ag.confirm_ticket(conv, fp).ticket_id.startswith("TKT-")


def fingerprint_of(state: str) -> str:
    conv = conv_state.load(state, main.fleet())
    assert conv is not None and conv.draft is not None
    return conv.draft.fingerprint


def test_empty_selection_does_not_send_everything(ml: MLClient, toir: ToirClient) -> None:
    """`keep_operations: []` — механик снял все работы: отказ, а не «весь состав». Поле не передано — весь состав."""
    bucket, counting = FakeBucket(), CountingToir(toir)
    a, _ = _instance(ml, counting, bucket, list(DRAFT_STEPS))
    vid, _ = ANOMALY
    a.cookies.set("dm_v2", "b" * 32)
    pending = _pending(a)
    url = f"/api/v2/tickets/{pending['pending_id']}/approve"
    r = a.post(url, json={"vehicle_id": vid, "keep_operations": [], "keep_spare_parts": []})
    assert r.status_code == 409 and "работ" in r.json()["detail"] and counting.sent == 0
    ok = a.post(url, json={"vehicle_id": vid})
    assert ok.status_code == 200 and counting.sent == 1


def test_removed_operation_takes_its_page_out_of_references(ml: MLClient, toir: ToirClient) -> None:
    """Механик убрал работу на листе заявки — страница, на которую ссылалась только она, в ТОиР не уходит."""
    from test_agent import TwoPageSearch

    ops = [
        {"text": "Замерить давление масла манометром", "ref": "R1"},
        {"text": "Затянуть пробку по руководству", "ref": "R2"},
    ]
    steps = [call("search_manual", query="масло"), call("draft_ticket", **{**DRAFT, "operations": ops}), say("ок")]
    ag, _ = make_agent(steps, ml, toir, TwoPageSearch())
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore())
    )
    c = TestClient(app)
    c.cookies.set("dm_v2", "c" * 32)
    pending = _pending(c)
    assert [r["pdf_page"] for r in pending["payload"]["references"]] == [42, 77]
    vid, _ = ANOMALY
    r = c.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid, "keep_operations": [0]})
    assert r.status_code == 200
    assert [x["pdf_page"] for x in r.json()["payload"]["references"]] == [42]
