"""Стоимость по участкам (issue #16): цены с кэшем провайдера, журнал, трасса с ₽ по шагам."""

from __future__ import annotations

import pytest

from service.clients import MLClient, ToirClient
from service.store import Store, cost_rub, price_table, prices
from test_agent import ANOMALY, ScriptedLLM, call, make_agent, say


def test_cached_input_is_cheaper() -> None:
    full = cost_rub("deepseek", 10_000, 500)
    half_cached = cost_rub("deepseek", 10_000, 500, tokens_cached=5_000)
    assert 0 < half_cached < full
    p = prices("deepseek")
    assert full == pytest.approx((10_000 * p.tokens_in + 500 * p.tokens_out) / 1e6)


def test_env_overrides_price(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRICE_IN_RUB", "1000")
    monkeypatch.setenv("LLM_PRICE_OUT_RUB", "0")
    monkeypatch.setenv("LLM_PRICE_CACHED_RUB", "0")
    assert cost_rub("deepseek", 1_000_000, 10, tokens_cached=500_000) == pytest.approx(500.0)


def test_every_price_has_source() -> None:
    t = price_table()
    for row in [*t["llm"].values(), *t["other"].values(), t["usd_rub"]]:
        assert row.get("source") and row.get("confidence")


def test_log_keeps_cached_tokens() -> None:
    st = Store(":memory:")
    cost = st.log_llm("r1", 1, "deepseek", "m", 1000, 100, 5, tokens_cached=800)
    row = st.llm_calls("r1")[0]
    assert row["tokens_cached"] == 800 and row["cost_rub"] == pytest.approx(cost)


def test_trace_has_rub_per_step_and_cached_total(ml: MLClient, toir: ToirClient) -> None:
    class CachingLLM(ScriptedLLM):
        def chat(self, messages, tools):  # type: ignore[no-untyped-def]
            reply = super().chat(messages, tools)
            reply.tokens_cached = 600
            return reply

    steps = [call("get_diagnosis", vehicle_id=ANOMALY[0], session_id=ANOMALY[1]), say("Готово.")]
    ag, _ = make_agent(steps, ml, toir)
    ag.provider = CachingLLM(steps)
    reply = ag.ask(ag.start(*ANOMALY), "Что с двигателем?")
    llm_steps = [s for s in reply.trace["steps"] if s["kind"] == "llm"]
    assert len(llm_steps) == 2 and all(s["cost_rub"] > 0 and s["tokens_cached"] == 600 for s in llm_steps)
    assert reply.trace["tokens_cached"] == 1200
    total = sum(s["cost_rub"] for s in llm_steps)
    assert reply.trace["cost_rub"] == pytest.approx(total, abs=3e-4)  # шаги округлены до 4 знаков
