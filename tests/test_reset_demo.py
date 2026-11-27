"""`make reset-demo` (R3 демо-плана): после отправленной заявки — снова «Создать заявку»; чужое не тронуто.

Настоящий бакет здесь не нужен: нить и заявку создаёт тот же `/api/v2`, что на стенде, поверх бакета в памяти
(`ThreadStore` как на стенде) и SQLite в файле; отметку #104 кладём тем же ключом `v2/tickets/{отпечаток}.json`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import reset_demo
from reset_demo import DEFAULT, THREADS, ResetError, S3Objects, load_fleet, make_plan, parse_targets
from service import api_v2, main
from service.clients import MLClient, ToirClient
from service.store import Store
from test_agent import ANOMALY, DRAFT, call, make_agent, say

OTHER = ("P456AT178", "S-0002")  # не из списка: его нить, заявка и отметка должны остаться


class Memory:
    """Один словарь объектов — и как бакет `ThreadStore` (get бросает), и как `reset_demo.Objects`."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def thread_bucket(self) -> Any:
        mem = self

        class Bucket:
            def get(self, key: str) -> bytes:
                return mem.objects[key]

            def put(self, key: str, data: bytes, content_type: str = "") -> None:
                mem.objects[key] = data

        return Bucket()

    def keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture
def stand(ml: MLClient, toir: ToirClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    steps = [
        say("Давление масла на холостом ходу не менее 0,1 МПа [R1]."),
        call("search_manual", query="давление масла"),
        call("draft_ticket", **DRAFT),
        say("Черновик заявки готов [R1]."),
    ]
    ag, _ = make_agent(steps, ml, toir)
    db = tmp_path / "agent.db"
    ag.store = store = Store(db)
    mem = Memory()
    app = main.FastAPI()
    threads = api_v2.ThreadStore(mem.thread_bucket())
    app.include_router(api_v2.build_router(lambda: ag, lambda: store, main.fleet, lambda r: None, threads))
    c = TestClient(app)
    vid, sid = ANOMALY
    c.post(
        "/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Что с двигателем?", "new_thread": True}
    )
    r = c.post("/api/v2/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Создать заявку на дефектовку"})
    pending = next(json.loads(x[6:]) for x in r.text.split("\n") if '"ticket_pending"' in x)
    sent = c.post(f"/api/v2/tickets/{pending['pending_id']}/approve", json={"vehicle_id": vid}).json()
    assert sent["ticket_id"].startswith("TKT-")
    fp = store.tickets(vid)[0]["fingerprint"]
    mem.objects[f"v2/tickets/{fp}.json"] = json.dumps({"state": "sent", "ticket_id": sent["ticket_id"]}).encode()
    # чужое: нить другой машины, её заявка в SQLite и отметка
    mem.objects[f"{THREADS}{'f' * 32}.json"] = json.dumps({"session_id": OTHER[1], "transcript": []}).encode()
    store.remember_ticket("TKT-9999", {**sent["payload"], "vehicle_id": OTHER[0], "session_id": OTHER[1]}, "other")
    mem.objects["v2/tickets/other.json"] = b'{"state": "sent", "ticket_id": "TKT-9999"}'
    return {"client": c, "mem": mem, "db": db, "store": store, "vid": vid, "sid": sid, "fp": fp, "sent": sent}


def test_default_list_is_in_the_fleet() -> None:
    targets = parse_targets(DEFAULT, load_fleet())
    by = {t.vehicle: t.sessions for t in targets}
    assert by["B418HK98"] == {"S-0009"} and by["M739BA198"] == {"S-0104"} and by["H142OX78"] == {"S-0113"}
    assert by["A427MA78"] == {"S-0030", "S-0031", "S-0032"}  # машина без проверки — все её проверки


def test_typo_is_an_error_not_nothing() -> None:
    with pytest.raises(ResetError, match="B418HK9"):
        parse_targets(["B418HK9/S-0009"], load_fleet())
    with pytest.raises(ResetError, match="нет проверки"):
        parse_targets(["B418HK98/S-0104"], load_fleet())  # проверка чужой машины


def test_plan_finds_thread_marker_and_rows_of_the_list_only(stand: dict[str, Any]) -> None:
    mem, vid, sid, fp = stand["mem"], stand["vid"], stand["sid"], stand["fp"]
    with sqlite3.connect(stand["db"]) as db:
        plan = make_plan(mem, db, parse_targets([f"{vid}/{sid}"], load_fleet()))
    assert [(v, s) for _, v, s, _ in plan.threads] == [(vid, sid)]
    assert [k for k, *_ in plan.marks] == [f"v2/tickets/{fp}.json"]
    assert {(r.table, r.vehicle, r.session) for r in plan.rows} == {("tickets", vid, sid), ("card_views", vid, sid)}
    assert plan.other_threads == 1 and plan.other_marks == ["v2/tickets/other.json"]


def test_marker_found_from_thread_alone(stand: dict[str, Any]) -> None:
    """На стенде SQLite экземпляра недоступна: отпечаток считается из заявки в стенограмме нити."""
    mem, vid, sid, fp = stand["mem"], stand["vid"], stand["sid"], stand["fp"]
    plan = make_plan(mem, None, parse_targets([f"{vid}/{sid}"], load_fleet()))
    assert [k for k, *_ in plan.marks] == [f"v2/tickets/{fp}.json"]
    assert stand["sent"]["ticket_id"] in plan.marks[0][3]


def test_dry_run_deletes_nothing_then_reset_brings_the_button_back(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mem, vid, sid, fp, c = stand["mem"], stand["vid"], stand["sid"], stand["fp"], stand["client"]
    monkeypatch.setenv("S3_BUCKET", "demo-bucket")
    monkeypatch.setattr(S3Objects, "from_env", classmethod(lambda cls, http: mem))
    before = dict(mem.objects)
    argv = ["--only", f"{vid}/{sid}", "--db", str(stand["db"])]

    assert reset_demo.main([*argv, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert mem.objects == before and not mem.deleted
    assert f"v2/tickets/{fp}.json" in out and "будет удалено" in out and "Сухой прогон" in out
    assert len(stand["store"].tickets(vid)) == 1

    assert reset_demo.main(argv) == 0
    out = capsys.readouterr().out
    assert f"v2/tickets/{fp}.json" not in mem.objects
    assert not [k for k in mem.objects if k.startswith(THREADS) and json.loads(mem.objects[k])["session_id"] == sid]
    assert c.get(f"/api/v2/vehicles/{vid}/tickets").json() == []  # кнопка «Создать заявку» снова на экране
    # новый экземпляр (пустая память) нити из бакета не поднимет
    assert api_v2.ThreadStore(mem.thread_bucket()).get("any-browser-0000", vid) is None
    # чужое на месте
    assert "v2/tickets/other.json" in mem.objects and f"{THREADS}{'f' * 32}.json" in mem.objects
    assert [t["ticket_id"] for t in stand["store"].tickets(OTHER[0])] == ["TKT-9999"]
    assert "Итог (удалено): нитей 1, отметок заявок 1" in out and "gh workflow run stand.yml" in out


def test_s3_objects_sign_list_get_delete(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[tuple[str, str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, req.headers.get("authorization", "")))
        if req.method == "GET" and "list-type" in str(req.url):
            return httpx.Response(200, text="<ListBucketResult><Key>v2/threads/a.json</Key></ListBucketResult>")
        if req.method == "GET":
            return httpx.Response(404)
        return httpx.Response(204)

    monkeypatch.setenv("S3_BUCKET", "b")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "key-id-123")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "very-secret-456")
    objects = S3Objects.from_env(httpx.Client(transport=httpx.MockTransport(handler)))
    assert objects.keys("v2/threads/") == ["v2/threads/a.json"]
    assert objects.get("v2/threads/a.json") is None
    objects.delete("v2/threads/a.json")
    assert [m for m, _, _ in seen] == ["GET", "GET", "DELETE"]
    assert seen[-1][1] == "/b/v2/threads/a.json" and all(a.startswith("AWS4-HMAC-SHA256") for *_, a in seen)
    assert "very-secret-456" not in capsys.readouterr().out


def test_bucket_without_static_key_stops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("S3_BUCKET", "b")
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    assert reset_demo.main(["--dry-run", "--db", str(tmp_path / "none.db")]) == 2
