"""Состояние разговора без сервера: подписанная строка, которую клиент возвращает с каждым запросом.

Зачем: стенд — Serverless Containers; соседний запрос может попасть в другой экземпляр или после холодного старта,
и разговор в памяти процесса теряется («Отправить» → «разговор не найден»). Поэтому разговор (сообщения, найденные
фрагменты, черновик заявки) сериализуется, сжимается и подписывается HMAC-SHA256 ключом `APP_SECRET`.
Клиент строку не разбирает; изменить источники или черновик, не сломав подпись, нельзя.
Без `APP_SECRET` ключ случайный на процесс — локально этого хватает.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import zlib
from functools import lru_cache
from typing import Any

from service.agent import Conversation, Source, TicketDraft
from service.clients import ServiceError, TicketRequest
from service.fleet import Fleet
from service.llm import ToolCall

VERSION = 1


class StateError(ServiceError):
    http_status = 400


@lru_cache(maxsize=1)
def _key() -> bytes:
    secret = os.environ.get("APP_SECRET", "")
    return secret.encode("utf-8") if secret else secrets.token_bytes(32)


def sign_text(text: str) -> str:
    """Подпись текста, который сервер разрешает озвучить (#14): синтезируется только то, что собрал код."""
    return hmac.new(_key(), b"speech:" + text.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_text(text: str, sig: str) -> bool:
    return hmac.compare_digest(sign_text(text), sig)


def _msg_out(m: dict[str, Any]) -> dict[str, Any]:
    out = dict(m)
    if out.get("tool_calls"):
        out["tool_calls"] = [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in out["tool_calls"]]
    return out


def _msg_in(m: dict[str, Any]) -> dict[str, Any]:
    out = dict(m)
    if out.get("tool_calls"):
        out["tool_calls"] = [ToolCall(c["id"], c["name"], c["arguments"]) for c in out["tool_calls"]]
    return out


def dump(conv: Conversation) -> str:
    state = {
        "v": VERSION,
        "id": conv.id,
        "vehicle_id": conv.vehicle.vehicle_id,
        "session_id": conv.session_id,
        "messages": [_msg_out(m) for m in conv.messages],
        "sources": [s.__dict__ for s in conv.sources.values()],
        "draft": None
        if conv.draft is None
        else {
            "body": conv.draft.body.model_dump(),
            "urgency_reason": conv.draft.urgency_reason,
            "fingerprint": conv.draft.fingerprint,
            "tools": conv.draft.tools,
        },
    }
    raw = zlib.compress(json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    sig = hmac.new(_key(), raw, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(sig + raw).decode("ascii")


def load(token: str, fleet: Fleet) -> Conversation:
    try:
        blob = base64.urlsafe_b64decode(token.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise StateError("Разговор повреждён — откройте проверку заново.") from exc
    sig, raw = blob[:16], blob[16:]
    if not hmac.compare_digest(sig, hmac.new(_key(), raw, hashlib.sha256).digest()[:16]):
        raise StateError("Разговор устарел или повреждён — откройте проверку заново.")
    state = json.loads(zlib.decompress(raw).decode("utf-8"))
    if state.get("v") != VERSION:
        raise StateError("Разговор от старой версии сервиса — откройте проверку заново.")
    vehicle = fleet.vehicle(state["vehicle_id"])
    if vehicle is None:
        raise StateError("Машина из разговора не найдена.")
    conv = Conversation(id=state["id"], vehicle=vehicle, session_id=state["session_id"])
    conv.messages = [_msg_in(m) for m in state["messages"]]
    conv.sources = {s["ref"]: Source(**s) for s in state["sources"]}
    d = state.get("draft")
    if d:
        conv.draft = TicketDraft(
            body=TicketRequest.model_validate(d["body"]),
            urgency_reason=d["urgency_reason"],
            fingerprint=d["fingerprint"],
            tools=list(d.get("tools") or []),
        )
    return conv
