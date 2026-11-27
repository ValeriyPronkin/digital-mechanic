"""DeepSeek через Anthropic-совместимый адрес (LLM_API=anthropic), как у Никиты."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from service.llm import DeepSeekAnthropicProvider, DeepSeekProvider, ToolCall, ToolSpec, provider_from_env

THINK = {"type": "thinking", "thinking": "нужен поиск", "signature": "sig"}


def _provider(replies: list[dict[str, Any]], seen: list[dict[str, Any]]) -> DeepSeekAnthropicProvider:
    def handle(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/anthropic/v1/messages" and req.headers["x-api-key"] == "k"
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=replies[len(seen) - 1])

    http = httpx.Client(base_url=DeepSeekAnthropicProvider.BASE_URL, transport=httpx.MockTransport(handle))
    return DeepSeekAnthropicProvider(api_key="k", http=http)


def test_selected_by_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.delenv("LLM_API", raising=False)
    assert type(provider_from_env()) is DeepSeekProvider  # по умолчанию — как было
    monkeypatch.setenv("LLM_API", "anthropic")
    assert isinstance(provider_from_env(), DeepSeekAnthropicProvider)


def test_tool_round_keeps_thinking_and_merges_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_EFFORT", "low")
    seen: list[dict[str, Any]] = []
    first = {
        "model": "deepseek-chat",
        "content": [THINK, {"type": "tool_use", "id": "t1", "name": "search_manual", "input": {"query": "масло"}}],
        "usage": {"input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 30},
        "stop_reason": "tool_use",
    }
    second = {"content": [{"type": "text", "text": "Ответ [R1]."}], "usage": {}, "stop_reason": "end_turn"}
    p = _provider([first, second], seen)
    tools = [ToolSpec("search_manual", "поиск", {"type": "object", "properties": {}})]
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": "правила"},
        {"role": "system", "content": "контекст"},
        {"role": "user", "content": "вопрос"},
    ]
    r1 = p.chat(msgs, tools, max_tokens=900)
    assert r1.tool_calls == [ToolCall("t1", "search_manual", {"query": "масло"})]
    assert (r1.tokens_in, r1.tokens_cached, r1.tokens_out) == (150, 50, 30)
    assert seen[0]["system"] == "правила\n\nконтекст" and seen[0]["output_config"] == {"effort": "low"}
    assert seen[0]["max_tokens"] == 900 + 3000 and seen[0]["tools"][0]["input_schema"]
    msgs += [
        {"role": "assistant", "content": "", "tool_calls": r1.tool_calls},
        {"role": "tool", "tool_call_id": "t1", "name": "search_manual", "content": "{}"},
        {"role": "user", "content": "ещё"},
    ]
    r2 = p.chat(msgs, tools)
    assert r2.content == "Ответ [R1]." and not r2.truncated
    wire = seen[1]["messages"]
    assert [m["role"] for m in wire] == ["user", "assistant", "user"]
    assert wire[1]["content"][0] == THINK  # рассуждение возвращается как есть
    assert [b["type"] for b in wire[2]["content"]] == ["tool_result", "text"]  # результат и вопрос — один ход


def test_without_effort_no_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_EFFORT", raising=False)
    seen: list[dict[str, Any]] = []
    p = _provider([{"content": [{"type": "text", "text": "да"}], "usage": {}, "stop_reason": "max_tokens"}], seen)
    r = p.chat([{"role": "user", "content": "вопрос"}], [], max_tokens=300)
    assert r.truncated and "output_config" not in seen[0] and "tools" not in seen[0] and seen[0]["max_tokens"] == 300


def test_code_turn_gets_thinking_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_EFFORT", "low")
    seen: list[dict[str, Any]] = []
    p = _provider([{"content": [{"type": "text", "text": "ок"}], "usage": {}, "stop_reason": "end_turn"}], seen)
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": "вопрос"},
        {"role": "assistant", "content": "", "tool_calls": [ToolCall("pre-diag", "get_diagnosis", {})]},
        {"role": "tool", "tool_call_id": "pre-diag", "name": "get_diagnosis", "content": "{}"},
    ]
    p.chat(msgs, [])
    first = seen[0]["messages"][1]["content"][0]
    assert first["type"] == "thinking" and first["thinking"]  # предвыборка кода — с пометкой, иначе API отвечает 400
