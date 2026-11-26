"""Провайдеры модели: перевод сообщений и разбор вызовов инструментов без сети (MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest

from service.llm import DeepSeekProvider, GigaChatProvider, LLMError, ToolCall, ToolSpec, provider_from_env

TOOLS = [ToolSpec("search_manual", "поиск", {"type": "object", "properties": {"query": {"type": "string"}}})]
HISTORY = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "вопрос"},
    {"role": "assistant", "content": "", "tool_calls": [ToolCall("c1", "search_manual", {"query": "масло"})]},
    {"role": "tool", "tool_call_id": "c1", "name": "search_manual", "content": '{"found": []}'},
]


def test_deepseek_roundtrip() -> None:
    sent: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        sent.update(json.loads(req.content))
        sent["auth"] = req.headers["authorization"]
        fn = {"name": "search_manual", "arguments": '{"query": "зазор"}'}
        msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "x1", "type": "function", "function": fn}]}
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [{"message": msg}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            },
        )

    p = DeepSeekProvider("k", http=httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler)))
    r = p.chat(HISTORY, TOOLS)
    assert r.tool_calls == [ToolCall("x1", "search_manual", {"query": "зазор"})]
    assert (r.tokens_in, r.tokens_out) == (120, 30)
    wire = sent["messages"]
    assert isinstance(wire, list)
    assert wire[2]["tool_calls"][0]["function"]["arguments"] == '{"query": "масло"}'
    assert wire[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"found": []}'}
    assert sent["tools"][0]["function"]["name"] == "search_manual"  # type: ignore[index]
    assert sent["auth"] == "Bearer k"


def test_gigachat_roundtrip() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "oauth" in str(req.url):
            assert req.headers["authorization"] == "Basic creds"
            return httpx.Response(200, json={"access_token": "tok", "expires_at": 9_999_999_999_000})
        body = json.loads(req.content)
        assert req.headers["authorization"] == "Bearer tok"
        assert body["functions"][0]["name"] == "search_manual"
        assert body["messages"][2]["function_call"] == {"name": "search_manual", "arguments": {"query": "масло"}}
        assert body["messages"][3] == {"role": "function", "name": "search_manual", "content": '{"found": []}'}
        msg = {
            "role": "assistant",
            "content": "",
            "function_call": {"name": "search_manual", "arguments": {"query": "ремень"}},
            "functions_state_id": "st-1",
        }
        return httpx.Response(
            200,
            json={
                "model": "GigaChat-2-Max",
                "choices": [{"message": msg}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},
            },
        )

    p = GigaChatProvider("creds", http=httpx.Client(transport=httpx.MockTransport(handler)))
    r = p.chat(HISTORY, TOOLS)
    r2 = p.chat(HISTORY, TOOLS)
    assert r.tool_calls[0].name == "search_manual" and r.tool_calls[0].arguments == {"query": "ремень"}
    assert r.functions_state_id == "st-1" and r2.tokens_in == 50
    assert sum("oauth" in c for c in calls) == 1  # токен переиспользуется


def test_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "c")
    assert provider_from_env().name == "gigachat"
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    assert provider_from_env().name == "deepseek"
    monkeypatch.setenv("LLM_PROVIDER", "other")
    with pytest.raises(LLMError):
        provider_from_env()


def test_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(LLMError, match="DEEPSEEK_API_KEY"):
        DeepSeekProvider()


def test_http_error_is_llm_error() -> None:
    p = DeepSeekProvider(
        "k", http=httpx.Client(base_url="https://x", transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    )
    with pytest.raises(LLMError, match="401"):
        p.chat(HISTORY, TOOLS)


def test_gigachat_single_system_message_first() -> None:
    """GigaChat: «system message must be the first message» — промпт и контекст разговора — одним сообщением."""
    msgs = [
        {"role": "system", "content": "правила"},
        {"role": "system", "content": "контекст"},
        {"role": "user", "content": "вопрос"},
    ]
    wire = GigaChatProvider.to_wire(msgs)
    assert [m["role"] for m in wire] == ["system", "user"]
    assert wire[0]["content"] == "правила\n\nконтекст"
