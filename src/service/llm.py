"""Провайдеры модели с вызовом инструментов: `LLM_PROVIDER=deepseek|gigachat`.

Внутри агента — нейтральный формат сообщений (role system|user|assistant|tool), здесь он переводится
в формат провайдера: DeepSeek — OpenAI-совместимые `tools`/`tool_calls`, GigaChat — `functions`/`function_call`.
Ключи — только из окружения. GigaChat — через сертификат Минцифры (`service.tls`).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from service.clients import ServiceError
from service.tls import ssl_context

Message = dict[str, Any]
TIMEOUT = httpx.Timeout(60.0, connect=5.0)


class LLMError(ServiceError):
    http_status = 503


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0  # из tokens_in — попали в кэш провайдера (дешевле)
    model: str = ""
    functions_state_id: str | None = None  # GigaChat: вернуть в следующем ходе


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


class LLMProvider(Protocol):
    name: str
    model: str

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> LLMReply: ...


def _args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return val if isinstance(val, dict) else {}


def _post(http: httpx.Client, url: str, **kw: Any) -> dict[str, Any]:
    for attempt in (1, 2):
        try:
            resp = http.post(url, **kw)
        except httpx.HTTPError as exc:
            if attempt == 2:
                raise LLMError("Модель недоступна. Попробуйте ещё раз через минуту.") from exc
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and attempt == 1:
            time.sleep(1.0)
            continue
        if resp.status_code != 200:
            raise LLMError(f"Модель ответила ошибкой {resp.status_code}.")
        data: dict[str, Any] = resp.json()
        return data
    raise LLMError("Модель недоступна.")  # pragma: no cover


class DeepSeekProvider:
    name = "deepseek"

    def __init__(self, api_key: str | None = None, model: str | None = None, http: httpx.Client | None = None) -> None:
        key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise LLMError("Не задан DEEPSEEK_API_KEY.")
        self.model = model or os.environ.get("LLM_MODEL") or "deepseek-chat"
        self.http = http or httpx.Client(base_url="https://api.deepseek.com", timeout=TIMEOUT)
        self._auth = {"Authorization": f"Bearer {key}"}

    @staticmethod
    def to_wire(messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                out.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or "",
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
                            }
                            for c in m["tool_calls"]
                        ],
                    }
                )
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> LLMReply:
        body = {
            "model": self.model,
            "messages": self.to_wire(messages),
            "tools": [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ],
            "temperature": 0.2,
        }
        data = _post(self.http, "/chat/completions", json=body, headers=self._auth)
        msg = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        return LLMReply(
            content=msg.get("content") or "",
            tool_calls=[
                ToolCall(c["id"], c["function"]["name"], _args(c["function"].get("arguments")))
                for c in msg.get("tool_calls") or []
            ],
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            tokens_cached=int(usage.get("prompt_cache_hit_tokens", 0)),
            model=str(data.get("model", self.model)),
        )


class GigaChatProvider:
    name = "gigachat"
    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    API_URL = "https://gigachat.devices.sberbank.ru/api/v1"

    def __init__(
        self, credentials: str | None = None, model: str | None = None, http: httpx.Client | None = None
    ) -> None:
        creds = credentials or os.environ.get("GIGACHAT_CREDENTIALS", "")
        if not creds:
            raise LLMError("Не задан GIGACHAT_CREDENTIALS.")
        self._creds = creds
        self.scope = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
        self.model = model or os.environ.get("LLM_MODEL") or "GigaChat-2-Max"
        self.http = http or httpx.Client(timeout=TIMEOUT, verify=ssl_context())
        self._token = ""
        self._token_exp = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        data = _post(
            self.http,
            self.OAUTH_URL,
            data={"scope": self.scope},
            headers={"Authorization": f"Basic {self._creds}", "RqUID": str(uuid.uuid4()), "Accept": "application/json"},
        )
        self._token = str(data["access_token"])
        self._token_exp = float(data.get("expires_at", 0)) / 1000 or time.time() + 1500
        return self._token

    @staticmethod
    def to_wire(messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                c = m["tool_calls"][0]  # GigaChat вызывает одну функцию за ход
                item: dict[str, Any] = {
                    "role": "assistant",
                    "content": m.get("content") or "",
                    "function_call": {"name": c.name, "arguments": c.arguments},
                }
                if m.get("functions_state_id"):
                    item["functions_state_id"] = m["functions_state_id"]
                out.append(item)
            elif m["role"] == "tool":
                out.append({"role": "function", "name": m["name"], "content": m["content"]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> LLMReply:
        body = {
            "model": self.model,
            "messages": self.to_wire(messages),
            "functions": [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools],
            "function_call": "auto",
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        data = _post(self.http, f"{self.API_URL}/chat/completions", json=body, headers=headers)
        msg = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        calls = []
        if msg.get("function_call"):
            fc = msg["function_call"]
            calls.append(ToolCall(f"call_{uuid.uuid4().hex[:8]}", fc["name"], _args(fc.get("arguments"))))
        reply = LLMReply(
            content=msg.get("content") or "",
            tool_calls=calls,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            tokens_cached=int(usage.get("precached_prompt_tokens", 0)),
            model=str(data.get("model", self.model)),
            functions_state_id=msg.get("functions_state_id"),
        )
        return reply


def provider_from_env() -> LLMProvider:
    name = os.environ.get("LLM_PROVIDER", "deepseek").strip().lower()
    if name == "deepseek":
        return DeepSeekProvider()
    if name == "gigachat":
        return GigaChatProvider()
    raise LLMError(f"Неизвестный LLM_PROVIDER={name}: ожидается deepseek или gigachat.")
