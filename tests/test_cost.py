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


def test_every_price_is_official_and_dated() -> None:
    """#19: только официальные страницы; курс — ЦБ на 26.11.2026; суммы — без НДС."""
    t = price_table()
    for row in [*t["llm"].values(), *t["other"].values(), t["usd_rub"], t["vat_rate"]]:
        src = str(row.get("source", ""))
        assert src.startswith("https://"), row
        assert not any(bad in src for bad in ("costgoat", "aipricing", "pawetta")), src  # вторичные — нельзя
    assert t["usd_rub"]["date"] == "2026-11-26" and "cbr.ru" in t["usd_rub"]["source"]


def test_rub_prices_are_without_vat() -> None:
    from service.store import ex_vat

    assert ex_vat(122.0, vat_included=True) == pytest.approx(100.0)
    assert ex_vat(1.0, vat_included=False) == 1.0
    giga = prices("gigachat")  # 650 ₽ с НДС за 1 млн → без НДС
    assert giga.tokens_in == pytest.approx(650 / 1.22)


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


def test_deepseek_sends_max_tokens_and_reports_cache_and_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    import httpx

    from service.llm import DeepSeekProvider

    monkeypatch.setenv("LLM_MAX_TOKENS", "321")
    sent: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        sent.update(json.loads(req.content))
        body = {
            "model": "m",
            "choices": [{"message": {"role": "assistant", "content": "длинный ответ"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 321, "prompt_cache_hit_tokens": 900},
        }
        return httpx.Response(200, json=body)

    p = DeepSeekProvider("k", http=httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler)))
    r = p.chat([{"role": "user", "content": "?"}], [])
    assert sent["max_tokens"] == 321
    assert r.tokens_cached == 900 and r.truncated


def test_truncated_answer_is_marked(ml: MLClient, toir: ToirClient) -> None:
    long = say("Наблюдения: давление масла ниже нормы")
    long.truncated = True
    ag, _ = make_agent([long], ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Что с двигателем?")
    assert "сокращён по длине" in reply.text


def test_prefetch_answers_in_one_model_call(ml: MLClient, toir: ToirClient) -> None:
    """Код сам даёт модели диагноз и 3 фрагмента: при отклонении хватает одного вызова модели."""
    ag, llm = make_agent([say("Давление масла ниже нормы [R1].")], ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Что с двигателем?")
    assert len(llm.seen) == 1
    tools = [s["name"] for s in reply.trace["steps"] if s["kind"] == "tool"]
    assert tools == ["get_diagnosis (код)", "search_manual (код)"]
    assert reply.grounded


def test_prefetch_does_not_search_for_normal_or_failed(ml: MLClient, toir: ToirClient) -> None:
    from test_agent import FAILED, NORMAL

    for pair in (NORMAL, FAILED):
        ag, _ = make_agent([say("ок")], ml, toir)
        reply = ag.ask(ag.start(*pair), "Что с двигателем?")
        assert [s["name"] for s in reply.trace["steps"] if s["kind"] == "tool"] == ["get_diagnosis (код)"]


def test_diagnosis_prefetched_once_per_conversation(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Раз."), say("Два.")], ml, toir)
    conv = ag.start(*ANOMALY)
    ag.ask(conv, "Что с двигателем?")
    second = ag.ask(conv, "А что проверить?")
    assert "get_diagnosis (код)" not in [s["name"] for s in second.trace["steps"]]


def test_model_sees_short_fragment_numbers_checked_against_full(ml: MLClient, toir: ToirClient) -> None:
    import json

    from test_agent import FixtureSearch

    long_text = "Общие сведения о системе. " * 40 + "Давление масла на холостом ходу не менее 0,1 МПа."
    steps = [call("search_manual", query="давление масла холостой ход"), say("Не менее 0,1 МПа [R1].")]
    ag, llm = make_agent(steps, ml, toir, FixtureSearch(long_text), prefetch=False)
    reply = ag.ask(ag.start(*ANOMALY), "Какое давление масла?")
    tool = next(m for m in llm.seen[-1] if m["role"] == "tool")
    found = json.loads(str(tool["content"]))["found"][0]["text"]
    assert len(found) <= 450 and "0,1 МПа" in found
    assert "0,1 МПа" in reply.text


def test_ticket_request_does_not_prefetch_search(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("ок")], ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Оформи заявку")
    assert "search_manual (код)" not in [s["name"] for s in reply.trace["steps"]]


def test_prefetch_is_one_call_per_turn_for_gigachat(ml: MLClient, toir: ToirClient) -> None:
    """GigaChat принимает одну функцию за ход: каждый предварительный вызов — отдельный ход с ответом."""
    from service.llm import GigaChatProvider

    ag, llm = make_agent([say("ок")], ml, toir)
    ag.ask(ag.start(*ANOMALY), "Что с двигателем?")
    wire = GigaChatProvider.to_wire(llm.seen[0])
    calls = [m for m in wire if m.get("function_call")]
    results = [m for m in wire if m["role"] == "function"]
    assert len(calls) == len(results) == 2
    for i, m in enumerate(wire):
        if m.get("function_call"):
            assert wire[i + 1]["role"] == "function" and wire[i + 1]["name"] == m["function_call"]["name"]
