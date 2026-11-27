"""Главный механик (issue #21): статусы парка правилом, сводка, график оценки, API, инструмент агента."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from service import main
from service.compat import is_compatible
from service.fleet import Fleet, Session, Vehicle, fleet
from service.fleet_status import (
    TREND_DOWN,
    TREND_FLAT,
    TREND_UP,
    ordered,
    summary,
    trend,
    vehicle_status,
)

client = TestClient(main.app)
CRITICAL = {"F02", "F03", "F14"}
HARMLESS = {"F05", "F11"}  # класс 1: двигателю не грозит — не выше среднего


def expected_status(v: Vehicle) -> str:
    """Правило из issue #21, записанное в тесте независимо от кода."""
    last = max(v.sessions, key=lambda s: s.checked_at)
    if last.status == "check_failed":
        return "rerecord"
    if last.status == "anomaly":
        code = last.anomaly_type or ""
        if code and not is_compatible(code, v.engine_model):
            return "quarantine"
        doubtful = (last.confidence or 0) < 0.6 or last.signal_quality == "warning"
        if code in CRITICAL or ((last.anomaly_score or 0) >= 0.85 and code not in HARMLESS and not doubtful):
            return "quarantine"
        return "attention"
    if last.signal_quality == "warning" or (last.anomaly_score or 0) >= 0.30:
        return "attention"
    return "normal"


@pytest.mark.materials
def test_summary_of_50_vehicles_matches_rule() -> None:
    f = fleet()
    s = summary(f)
    assert s["total"] == 50 and sum(s["counts"].values()) == 50
    got = {r["vehicle_id"]: r["status"] for r in [*s["priority"], *s["normal"]]}
    assert got == {v.vehicle_id: expected_status(v) for v in f.vehicles}
    for k in ("quarantine", "attention", "rerecord", "normal"):
        assert s["counts"][k] == sum(1 for x in got.values() if x == k)


@pytest.mark.materials
def test_priority_order_and_reasons() -> None:
    s = summary(fleet())
    order = {"quarantine": 0, "attention": 1, "rerecord": 2}
    ranks = [order[r["status"]] for r in s["priority"]]
    assert ranks == sorted(ranks) and "normal" not in {r["status"] for r in s["priority"]}
    assert all(r["reasons"] for r in s["priority"])  # у каждой строки — почему


@pytest.mark.materials
def test_incompatible_code_is_quarantine() -> None:
    for v in fleet().vehicles:
        last = ordered(v)[-1]
        if last.status == "anomaly" and last.anomaly_type and not is_compatible(last.anomaly_type, v.engine_model):
            st = vehicle_status(v, fleet().fault_titles)
            assert st.status == "quarantine" and "повторная проверка" in st.reasons[0]


def _vehicle(vid: str, scores: list[float | None]) -> Vehicle:
    sessions = []
    for i, sc in enumerate(scores):
        failed = sc is None
        sessions.append(
            Session(
                session_id=f"T-{vid}-{i}",
                vehicle_id=vid,
                checked_at=f"2026-11-{10 + i:02d}T10:00:00+03:00",
                status="check_failed" if failed else ("anomaly" if sc >= 0.5 else "normal"),  # type: ignore[operator]
                anomaly_type=None if failed or sc < 0.5 else "F01",  # type: ignore[operator]
                anomaly_title=None,
                anomaly_score=sc,
                confidence=0.8,
                signal_quality="bad" if failed else "good",
                description="",
                model_version="t",
            )
        )
    return Vehicle(vehicle_id=vid, garage_no="Г-0", make="МАЗ", model=None, vehicle_type="грузовой",
                   engine_model="ЯМЗ-536", fuel="дизель", sessions=sessions)  # fmt: skip


def test_five_decreasing_vehicles_say_not_repaired() -> None:
    rows = [
        [0.82, 0.70, 0.55],
        [0.66, 0.51, 0.40, 0.31],
        [0.90, None, 0.62, 0.40, 0.20],
        [0.45, 0.38, 0.30, 0.22, 0.12],
        [0.77, 0.60, 0.05],
    ]
    for i, scores in enumerate(rows):
        assert trend(_vehicle(f"D{i}", scores))["trend"] == TREND_DOWN == "снижается — это не значит исправно"


def test_trend_up_flat_and_failed_check_is_a_gap() -> None:
    assert trend(_vehicle("U", [0.10, 0.12, 0.40]))["trend"] == TREND_UP
    assert trend(_vehicle("F", [0.20, 0.22, 0.18, 0.21]))["trend"] == TREND_FLAT
    t = trend(_vehicle("G", [0.30, None, 0.35]))
    assert [p["score"] for p in t["points"]] == [0.30, None, 0.35]  # сбой — разрыв, а не ноль


@pytest.mark.materials
def test_real_vehicle_with_failed_check_in_the_middle() -> None:
    v = fleet().vehicle("A464EP47")
    assert v is not None
    t = trend(v)
    scores = [p["score"] for p in t["points"]]
    assert None in scores[1:-1] and 0 not in scores
    assert t["trend"] == TREND_DOWN  # 0,77 → 0,04 после отклонения — не значит исправно


@pytest.mark.materials
def test_api_summary_vehicle_and_page() -> None:
    s = client.get("/api/fleet").json()
    assert s["total"] == 50 and s["priority"][0]["status"] == "quarantine"
    vid = s["priority"][0]["vehicle_id"]
    v = client.get(f"/api/fleet/{vid}").json()
    dates = [h["checked_at"] for h in v["history"]]
    assert dates == sorted(dates, reverse=True)  # история — новые сверху
    assert 3 <= len(v["trend"]["points"]) <= 5 and v["trend"]["trend"]
    assert v["tickets"] == [] or "ticket_id" in v["tickets"][0]
    assert client.get("/api/fleet/NOPE").status_code == 404
    page = client.get("/fleet")
    assert page.status_code == 200 and 'href="/v1"' in page.text and "/api/fleet" in page.text
    assert 'href="/fleet"' in client.get("/v1").text  # ссылка с прежней главной


def test_agent_tool_returns_same_summary(ml, toir) -> None:  # type: ignore[no-untyped-def]
    from test_agent import ANOMALY, call, make_agent, say

    ag, llm = make_agent([call("fleet_summary"), say("ок")], ml, toir, prefetch=False)
    ag.ask(ag.start(*ANOMALY), "Как парк?")
    tool = json.loads(next(m for m in llm.seen[-1] if m["role"] == "tool")["content"])
    full = summary(fleet())
    assert tool["counts"] == {full["labels"][k]: n for k, n in full["counts"].items()}
    assert [r["vehicle_id"] for r in tool["priority"]] == [r["vehicle_id"] for r in full["priority"][:10]]
    assert isinstance(Fleet, type)


def test_fleet_numbers_in_answer_are_not_cut(ml, toir) -> None:  # type: ignore[no-untyped-def]
    """Живой прогон: ответ о парке (номера машин, счётчики) вырезался проверкой цифр — это факты из кода."""
    from test_agent import ANOMALY, call, make_agent, say

    full = summary(fleet())
    first = full["priority"][0]
    text = (
        f"В карантине {full['counts']['quarantine']} машин. Первая — {first['garage_no']} ({first['vehicle_id']}): "
        f"{first['reasons'][0]}."
    )
    ag, _ = make_agent([call("fleet_summary"), say(text)], ml, toir, prefetch=False)
    reply = ag.ask(ag.start(*ANOMALY), "Что по парку?")
    assert first["vehicle_id"] in reply.text and str(full["counts"]["quarantine"]) in reply.text
    assert not any("убрал" in n for n in reply.notes)
