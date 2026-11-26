"""Общий счётчик расходов стенда (issue #11): условная запись с повтором, без потери сумм, сутки по Москве."""

from __future__ import annotations

import json
import threading
from datetime import datetime

import httpx
import pytest

from service.agent import BudgetExceededError
from service.clients import MLClient, ToirClient
from service.spend import MSK, BucketObject, RefreshingIamAuth, SharedLedger, moscow_day
from test_agent import ANOMALY, make_agent, say


class FakeObject:
    """Объект бакета с ETag и атомарной условной записью (как обещает S3: If-Match / If-None-Match: *)."""

    def __init__(self, conflicts: list[int] | None = None) -> None:
        self.data: bytes | None = None
        self.version = 0
        self.lock = threading.Lock()
        self.conflicts = list(conflicts or [])  # статусы «чужая запись успела раньше» перед честной записью
        self.down = False
        self.writes = 0

    def read(self) -> tuple[bytes | None, str | None]:
        if self.down:
            raise httpx.ConnectError("бакет недоступен")
        with self.lock:
            return self.data, (f'"v{self.version}"' if self.data is not None else None)

    def write(self, data: bytes, if_match: str | None) -> int:
        if self.down:
            raise httpx.ConnectError("бакет недоступен")
        with self.lock:
            if self.conflicts:
                return self.conflicts.pop(0)
            current = f'"v{self.version}"' if self.data is not None else None
            if if_match != current:
                return 412
            self.data, self.version = data, self.version + 1
            self.writes += 1
            return 200

    def total(self) -> float:
        return float(json.loads(self.data or b"{}").get("total_rub", 0.0))


TS = datetime(2026, 11, 26, 15, 0, tzinfo=MSK).timestamp()


def ledger(obj: FakeObject) -> SharedLedger:
    return SharedLedger(obj, clock=lambda: TS, sleep=lambda _: None)


def test_two_instances_share_one_counter() -> None:
    obj = FakeObject()
    a, b = ledger(obj), ledger(obj)
    a.add(0.30, TS)
    b.add(0.20, TS)
    assert a.spent_total() == pytest.approx(0.50) and b.spent_today(TS) == pytest.approx(0.50)


def test_parallel_writes_lose_nothing() -> None:
    """4 экземпляра × 2 потока × 50 прибавок по 0,01 ₽ одновременно → ровно 4,00 ₽."""
    obj = FakeObject()
    instances = [ledger(obj) for _ in range(4)]

    def work(inst: SharedLedger) -> None:
        for _ in range(50):
            inst.add(0.01, TS)

    threads = [threading.Thread(target=work, args=(inst,)) for inst in instances for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert obj.total() == pytest.approx(4.00, abs=1e-9)
    assert json.loads(obj.data or b"{}")["days"][moscow_day(TS)] == pytest.approx(4.00, abs=1e-9)


@pytest.mark.parametrize("status", [412, 409])
def test_conflict_is_retried(status: int) -> None:
    obj = FakeObject(conflicts=[status, status])
    led = ledger(obj)
    led.add(1.5, TS)
    assert obj.total() == pytest.approx(1.5) and obj.writes == 1


def test_bucket_down_keeps_sum_and_flushes_later() -> None:
    obj = FakeObject()
    led = ledger(obj)
    led.add(1.0, TS)
    obj.down = True
    led.add(2.0, TS)  # не записалось, но не потерялось
    assert led.spent_total() == pytest.approx(3.0)  # последнее прочитанное + накопленное
    obj.down = False
    led.add(0.5, TS)
    assert obj.total() == pytest.approx(3.5)


def test_day_is_moscow() -> None:
    late = datetime(2026, 11, 26, 23, 59, tzinfo=MSK).timestamp()
    early = datetime(2026, 11, 27, 0, 1, tzinfo=MSK).timestamp()
    obj = FakeObject()
    led = ledger(obj)
    led.add(1.0, late)
    led.add(2.0, early)
    assert led.spent_today(late) == pytest.approx(1.0) and led.spent_today(early) == pytest.approx(2.0)
    assert led.spent_total() == pytest.approx(3.0)


def test_agent_limits_use_shared_counter(ml: MLClient, toir: ToirClient) -> None:
    obj = FakeObject()
    other_instance = ledger(obj)
    other_instance.add(99.99, TS)  # другой экземпляр стенда почти выбрал дневной лимит
    ag, _ = make_agent([say("ок")], ml, toir, ledger=ledger(obj), clock=lambda: TS, budget_day_rub=100.0)
    reply = ag.ask(ag.start(*ANOMALY), "Что с двигателем?")
    assert obj.total() == pytest.approx(99.99 + reply.trace["cost_rub"], abs=1e-3)  # вызов модели — в общий счётчик
    with pytest.raises(BudgetExceededError, match="Лимит на сегодня"):
        ag.ask(ag.start(*ANOMALY), "И ещё?")


def test_bucket_object_sends_conditions() -> None:
    from service.kb_store import Bucket

    seen: list[tuple[str, dict[str, str]]] = []
    store: dict[str, bytes] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, dict(req.headers)))
        if req.method == "GET":
            return httpx.Response(200, content=store["x"], headers={"ETag": '"e1"'}) if store else httpx.Response(404)
        store["x"] = req.content
        return httpx.Response(200)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    obj = BucketObject(Bucket("b", lambda m, u, h, s: {**h, "X-YaCloud-SubjectToken": "t"}, http, "https://s3"))
    led = SharedLedger(obj, sleep=lambda _: None)
    led.add(1.0, TS)
    led.add(2.0, TS)
    puts = [h for m, h in seen if m == "PUT"]
    assert puts[0]["if-none-match"] == "*" and "if-match" not in puts[0]  # первый раз — объекта ещё нет
    assert puts[1]["if-match"] == '"e1"'  # дальше — только поверх прочитанной версии
    assert all(h["x-yacloud-subjecttoken"] == "t" for _, h in seen)


def test_iam_token_is_refreshed() -> None:
    tokens = iter(["t1", "t2"])

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Metadata-Flavor"] == "Google"
        return httpx.Response(200, json={"access_token": next(tokens)})

    now = [0.0]
    auth = RefreshingIamAuth(httpx.Client(transport=httpx.MockTransport(handler)), clock=lambda: now[0])
    assert auth("GET", "u", {}, "")["X-YaCloud-SubjectToken"] == "t1"
    now[0] = 60
    assert auth("GET", "u", {}, "")["X-YaCloud-SubjectToken"] == "t1"  # ещё свежий
    now[0] = RefreshingIamAuth.TOKEN_TTL + 61
    assert auth("GET", "u", {}, "")["X-YaCloud-SubjectToken"] == "t2"


def test_search_plan_call_goes_to_shared_counter(ml: MLClient, toir: ToirClient) -> None:
    """План поиска (#28) — тоже вызов модели: его стоимость — в общий счётчик, иначе расход стенда мимо лимита."""
    from service.llm import LLMReply

    obj = FakeObject()
    plan = LLMReply('{"lang": "ru", "queries": ["зазор клапанов"]}')
    ag, _ = make_agent([plan, say("ок")], ml, toir, ledger=ledger(obj), clock=lambda: TS, plan_search=True)
    reply = ag.ask(ag.start(*ANOMALY), "Какой зазор клапанов?")
    llm_steps = [s for s in reply.trace["steps"] if s["kind"] == "llm"]
    assert len(llm_steps) == 2 and any("план поиска" in s["name"] for s in llm_steps)
    assert obj.total() == pytest.approx(sum(s["cost_rub"] for s in llm_steps), abs=1e-3)
