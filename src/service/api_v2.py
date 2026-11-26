"""Слой совместимости для интерфейса v2 (issue #52, `web/` — автор Никита Пронкин): его API поверх нашей логики.

Маршруты — в форме `web/src/api.ts` Никиты под префиксом `/api/v2`. Ни одно наше правило здесь не меняется:
вердикт — наша карточка (`verdict_policy`), ответ — наш агент с проверкой цифр и ссылок (`agent.guard`),
заявка — наш черновик с отпечатком (`confirm_ticket`), срочность — правило кода (D-6), парк — `fleet_status`.

Разговор у Никиты живёт на сервере («нить» по браузеру и машине), у нас — подписанная строка у клиента
(D-12). Здесь нить хранит ту же подписанную строку: в памяти экземпляра, а на стенде (`V2_STATE_BUCKET=1`) —
ещё и в бакете `v2/threads/` по IAM-токену, потому что запросы одного механика приходят на разные экземпляры.

Ссылки на страницы: у нас `[R1]`, у интерфейса — `[S1]`; переводятся в тексте и в списке источников.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import secrets
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from service import conv_state, passport
from service.agent import Agent, AgentReply, Conversation
from service.clients import ServiceError, TicketRequest
from service.fleet import Fleet, Vehicle
from service.fleet_status import STATUS_LABEL, trend, vehicle_status
from service.manuals.catalog import DOCS_BY_ID, documents_for_engine
from service.store import Store
from service.verdict_policy import URGENCY_ACTION, VerdictCard, urgency_for
from service.voice import speech_for

log = logging.getLogger(__name__)

COOKIE = "dm_v2"
URGENCY_WORD = {"high": "высокий", "medium": "средний", "low": "низкий"}
QUALITY_WORD = {"good": "запись чистая", "warning": "запись с помехами", "bad": "запись непригодна"}
_REF = re.compile(r"\[R(\d+)\]")


def handle(ref: str) -> str:
    """R3 → S3: так интерфейс v2 называет страницы, на которые сослался ответ."""
    return "S" + ref[1:] if ref.startswith("R") else ref


def to_handles(text: str) -> str:
    return _REF.sub(lambda m: f"[S{m.group(1)}]", text)


def short_name(manual_id: str, fallback: str) -> str:
    doc = DOCS_BY_ID.get(manual_id)
    if doc is None:
        return fallback
    kind = "РК" if doc.kind == "ремонт" else "РЭ"
    return f"{kind} {doc.engines[0] if doc.engines else ''}".strip()


# ---------- парк и машины ----------


def _session_brief(fleet: Fleet, v: Vehicle, s: Any) -> dict[str, Any]:
    from service.compat import check as compat_check

    fits = True
    if s.status == "anomaly" and s.anomaly_type:
        fits = compat_check(s.anomaly_type, v.engine_model).ok
    return {
        "session_id": s.session_id,
        "checked_at": s.checked_at,
        "status": s.status,
        "anomaly_type": s.anomaly_type,
        "anomaly_title": fleet.fault_titles.get(s.anomaly_type or "") if s.anomaly_type else None,
        "anomaly_score": s.anomaly_score,
        "signal_quality": s.signal_quality,
        "fits_engine": fits,
    }


def _fleet_view(fleet: Fleet, v: Vehicle) -> dict[str, Any]:
    st = vehicle_status(v, fleet.fault_titles)
    last = st.last
    urgency = None
    if last is not None and last.status == "anomaly" and st.status != "rerecord":
        urgency = urgency_for(last)[0]
    return {
        "status": None if st.status == "rerecord" else st.status,
        "label": STATUS_LABEL[st.status],
        "badges": [],
        "urgency": urgency,
        "session_id": last.session_id if last else None,
        "fault_title": fleet.fault_titles.get(last.anomaly_type or "") if last and last.anomaly_type else None,
        "anomaly_score": last.anomaly_score if last else None,
        "reason": "; ".join(st.reasons),
    }


def _vehicle(v: Vehicle) -> dict[str, Any]:
    return {
        "vehicle_id": v.vehicle_id,
        "garage_no": v.garage_no,
        "make": v.make,
        "model": v.model,
        "vehicle_type": v.vehicle_type,
        "engine_model": v.engine_model,
        "fuel": v.fuel,
    }


def vehicle_brief(fleet: Fleet, v: Vehicle) -> dict[str, Any]:
    sessions = sorted(v.sessions, key=lambda s: s.checked_at)
    return {
        **_vehicle(v),
        "sessions_count": len(sessions),
        "last_session": _session_brief(fleet, v, sessions[-1]) if sessions else None,
        "fleet": _fleet_view(fleet, v),
    }


def vehicle_detail(fleet: Fleet, v: Vehicle) -> dict[str, Any]:
    sessions = sorted(v.sessions, key=lambda s: s.checked_at)  # от старых к новым: интерфейс берёт последнюю
    manuals = [
        {"id": d.doc_id, "short": short_name(d.doc_id, d.designation), "title": d.designation, "pages": d.pages}
        for d in documents_for_engine(v.engine_model)
    ]
    return {
        **_vehicle(v),
        "sessions": [_session_brief(fleet, v, s) for s in sessions],
        "manuals": manuals,
        "fleet": _fleet_view(fleet, v),
        "trend": trend(v)["trend"],
    }


# ---------- нити разговора ----------


class ThreadStore:
    """Нить = текущий разговор браузера о машине: подписанное состояние нашего агента + стенограмма для экрана."""

    def __init__(self, bucket: Any = None) -> None:
        self.bucket = bucket
        self._mem: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(browser: str, vehicle_id: str) -> str:
        return hashlib.sha256(f"{browser}|{vehicle_id}".encode()).hexdigest()[:32]

    def get(self, browser: str, vehicle_id: str) -> dict[str, Any] | None:
        k = self.key(browser, vehicle_id)
        with self._lock:
            if k in self._mem:
                return self._mem[k]
        if self.bucket is None:
            return None
        try:
            data: dict[str, Any] = json.loads(self.bucket.get(f"v2/threads/{k}.json"))
        except Exception:  # нет нити или бакет недоступен
            return None
        with self._lock:
            self._mem[k] = data
        return data

    def put(self, browser: str, vehicle_id: str, data: dict[str, Any]) -> None:
        k = self.key(browser, vehicle_id)
        with self._lock:
            self._mem[k] = data
        if self.bucket is not None:
            try:  # синхронно: следующий запрос механика может прийти на другой экземпляр
                self.bucket.put(
                    f"v2/threads/{k}.json", json.dumps(data, ensure_ascii=False).encode(), "application/json"
                )
            except Exception as exc:
                log.warning("нить v2 не записана в бакет: %s", type(exc).__name__)

    @classmethod
    def from_env(cls) -> ThreadStore:
        if os.environ.get("V2_STATE_BUCKET", "") != "1" or not os.environ.get("S3_BUCKET", "").strip():
            return cls()
        import httpx

        from service import kb_store
        from service.spend import RefreshingIamAuth

        http = httpx.Client(timeout=10)
        endpoint = os.environ.get("S3_ENDPOINT", kb_store.DEFAULT_ENDPOINT)
        return cls(kb_store.Bucket(os.environ["S3_BUCKET"].strip(), RefreshingIamAuth(http), http, endpoint))


# ---------- блоки и события ----------


def verdict_case(card: VerdictCard) -> str:
    if card.status == "check_failed":
        return "failed"
    if card.status == "normal":
        return "normal_raised" if card.color == "yellow" else "normal"
    if not card.compatible:
        return "mismatch"
    if any("помех" in b.lower() for b in card.banners):
        return "preliminary"
    return "anomaly"


def urgency_view(card: VerdictCard) -> dict[str, Any] | None:
    if not card.urgency:
        return None
    return {
        "level": card.urgency,
        "word": URGENCY_WORD[card.urgency],
        "action": URGENCY_ACTION[card.urgency],
        "reasons": [r for r in [card.urgency_reason, card.trend] if r],
    }


def verdict_block(conv: Conversation) -> dict[str, Any] | None:
    card, diag = conv.card, conv.diag
    if card is None or diag is None:
        return None
    confidence = diag.confidence
    return {
        "kind": "verdict",
        "case": verdict_case(card),
        "headline": card.title,
        "lines": [card.action, *card.banners],
        "session_id": diag.session_id,
        "checked_at": next((s.checked_at for s in conv.vehicle.sessions if s.session_id == diag.session_id), ""),
        "status": diag.status,
        "fault_code": card.fault_code,
        "fault_title": card.fault_title,
        "anomaly_score": diag.anomaly_score,
        "confidence": confidence,
        "confidence_word": None
        if confidence is None
        else ("высокая" if confidence >= 0.8 else "средняя" if confidence >= 0.6 else "низкая"),
        "signal_quality": diag.signal_quality,
        "quality_word": QUALITY_WORD.get(diag.signal_quality, diag.signal_quality),
        "urgency": urgency_view(card),
        "description": diag.description,
        "foreign_text": getattr(card, "ml_injection", None),
        "model_version": diag.model_version,
    }


def source_items(reply: AgentReply, conv: Conversation) -> list[dict[str, Any]]:
    out = []
    for s in reply.sources:
        src = conv.sources.get(s["ref"])
        manual_id = src.manual_id if src else ""
        short = short_name(manual_id, s["manual"])
        out.append(
            {
                "handle": handle(s["ref"]),
                "manual_id": manual_id,
                "short": short,
                "chip": short,
                "designation": s["manual"],
                "pdf_page": s["pdf_page"],
            }
        )
    return out


_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def quote_line(answer: str, ref: str, source_text: str) -> str:
    """Строка страницы, на которой нашлось число из предложения ответа со ссылкой [ref] — её интерфейс v2
    показывает «Найдено на странице». Нет числа или строки — начало фрагмента."""
    from service.agent import numbers

    wanted: set[str] = set()
    for sentence in _SENTENCE.split(answer):
        if f"[{ref}]" in sentence:
            wanted |= numbers(sentence)
    lines = [ln.strip() for ln in source_text.splitlines() if ln.strip()]
    if wanted:
        best = max(lines, key=lambda ln: len(numbers(ln) & wanted), default="")
        if best and numbers(best) & wanted:
            return best[:240]
    return (lines[0] if lines else "")[:240]


def verification(reply: AgentReply, text: str) -> dict[str, Any]:
    """Что проверил код (`agent.guard`): страницы, на которые опирается ответ, и сколько снято. Наш guard не
    зачёркивает, а убирает предложение с цифрой не из фрагмента — оно считается снятым."""
    rules = reply.trace.get("rules") or {}
    verified = [handle(s["ref"]) for s in reply.sources]
    quotes = {handle(s["ref"]): quote_line(reply.text, s["ref"], s.get("quote") or "") for s in reply.sources}
    return {
        "type": "verification",
        "text": text,
        "verified": verified,
        "quotes": quotes,
        "counts": {
            "verified": len(verified),
            "unverified": int(rules.get("numbers_dropped") or 0),
            "uncited": int(rules.get("opinions_marked") or 0),
        },
        "withdrawn": [],
        "scanned": [],
    }


def usage_events(reply: AgentReply) -> list[dict[str, Any]]:
    return [
        {
            "type": "usage",
            "model": s.get("name", ""),
            # у нас tokens_in включает взятые из кэша провайдера, у интерфейса v2 они отдельно — без двойного счёта
            "input_tokens": max(0, int(s.get("tokens_in", 0)) - int(s.get("tokens_cached", 0))),
            "cache_write_tokens": 0,
            "cache_read_tokens": s.get("tokens_cached", 0),
            "output_tokens": s.get("tokens_out", 0),
            "latency_ms": s.get("ms", 0),
            "cost_usd": 0.0,
            "cost_rub": s.get("cost_rub", 0.0),
            "replayed": bool(reply.trace.get("cache")),
        }
        for s in reply.trace.get("steps") or []
        if s.get("kind") == "llm"
    ]


TOOL_LABEL = {
    "get_diagnosis": "Результат проверки",
    "vehicle_history": "История машины",
    "search_manual": "Ищу в руководстве",
    "draft_ticket": "Готовлю заявку",
    "fleet_summary": "Сводка парка",
}


def tool_events(reply: AgentReply, conv: Conversation, verdict_sent: bool) -> tuple[list[dict[str, Any]], bool]:
    events: list[dict[str, Any]] = []
    for n, s in enumerate(reply.trace.get("steps") or []):
        if s.get("kind") != "tool":
            continue
        name = s.get("tool") or s.get("name", "")
        tid = f"t{n}"
        block = None
        if name == "get_diagnosis" and not verdict_sent:
            block = verdict_block(conv)
            verdict_sent = block is not None
        events.append(
            {
                "type": "tool_started",
                "id": tid,
                "name": name,
                "label": TOOL_LABEL.get(name, name),
                "input": s.get("params") or {},
            }
        )
        events.append({"type": "tool_result", "id": tid, "name": name, "ok": bool(s.get("ok")), "block": block})
    if not verdict_sent and conv.card is not None:  # диагноз уже в разговоре: карточку всё равно показать один раз
        block = verdict_block(conv)
        if block is not None:
            events += [
                {
                    "type": "tool_started",
                    "id": "verdict",
                    "name": "get_diagnosis",
                    "label": TOOL_LABEL["get_diagnosis"],
                },
                {"type": "tool_result", "id": "verdict", "name": "get_diagnosis", "ok": True, "block": block},
            ]
            verdict_sent = True
    return events, verdict_sent


def ticket_pending(conv: Conversation) -> dict[str, Any] | None:
    d = conv.draft
    if d is None or conv.card is None:
        return None
    body = d.body.model_dump()
    card = conv.card
    warning = []
    if verdict_case(card) == "preliminary":
        warning.append("Запись с помехами: результат предварительный — подтвердите повторной записью.")
    if conv.diag and conv.diag.confidence is not None and conv.diag.confidence < 0.6:
        warning.append("Уверенность сервиса диагностики снижена — сначала уточнить дефектовкой.")
    level = body["urgency"]
    return {
        "type": "ticket_pending",
        "pending_id": d.fingerprint,
        "payload": body,
        "operations": [{"text": t, "source": "", "quote": "", "scanned": False} for t in body["operations"]],
        "spare_parts": [{"text": t, "source": "", "quote": "", "scanned": False} for t in body["spare_parts"]],
        "urgency": {
            "level": level,
            "word": URGENCY_WORD[level],
            "action": URGENCY_ACTION[level],
            "reasons": [d.urgency_reason],
        },
        # Приоритет — правило кода (D-6): механику показан один, предложенный; выбор другого — решение человека.
        "urgency_choices": [{"level": level, "word": URGENCY_WORD[level], "action": URGENCY_ACTION[level]}],
        "warning": warning,
    }


def ticket_view(row: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(row["body"])
    return {
        "id": row["id"],
        "ticket_id": row["ticket_id"],
        "vehicle_id": row["vehicle_id"],
        "session_id": row["session_id"],
        "created_at": datetime.fromtimestamp(row["ts"], UTC).isoformat(),
        "payload": payload,
        "urgency_proposed": row.get("urgency_proposed") or payload.get("urgency"),
        "outcome": row.get("outcome"),
        "outcome_note": row.get("outcome_note"),
    }


# ---------- маршруты ----------


class ChatIn(BaseModel):
    vehicle_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    new_thread: bool = False
    level: Literal["expert", "steps"] = "steps"  # уровень механика (#17): формат и длина ответа


class TicketDecision(BaseModel):
    vehicle_id: str = Field(min_length=1)
    keep_operations: list[int] = Field(default_factory=list)
    keep_spare_parts: list[int] = Field(default_factory=list)
    warning_acknowledged: bool = False
    urgency: Literal["low", "medium", "high"] | None = None


class OutcomeIn(BaseModel):
    outcome: Literal["confirmed", "not_confirmed", "other_fault"]
    note: str | None = Field(default=None, max_length=1000)


def build_router(
    get_agent: Callable[[], Agent],
    get_store: Callable[[], Store],
    get_fleet: Callable[[], Fleet],
    rate_limit: Callable[[Request], None],
    threads: ThreadStore,
    get_speech: Callable[[], Any] | None = None,
    get_pages: Callable[[], Any] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v2")

    def browser(request: Request) -> str | None:
        b = request.cookies.get(COOKIE, "")
        return b if b.isalnum() and 16 <= len(b) <= 64 else None

    def vehicle_or_404(vehicle_id: str) -> Vehicle:
        v = get_fleet().vehicle(vehicle_id)
        if v is None:
            raise HTTPException(404, f"Машина {vehicle_id} не найдена в парке.")
        return v

    @router.get("/vehicles")
    def vehicles() -> list[dict[str, Any]]:
        f = get_fleet()
        return [vehicle_brief(f, v) for v in f.vehicles]

    @router.get("/fleet")
    def fleet() -> dict[str, Any]:
        f = get_fleet()
        briefs = [vehicle_brief(f, v) for v in f.vehicles]
        order = {"quarantine": 0, "attention": 1, None: 2, "normal": 3}
        briefs.sort(key=lambda b: (order.get(b["fleet"]["status"], 2), -(b["fleet"]["anomaly_score"] or 0)))
        counts: dict[str, int] = {"normal": 0, "attention": 0, "quarantine": 0, "no_valid_check": 0}
        for b in briefs:
            counts[b["fleet"]["status"] or "no_valid_check"] += 1
        rows = get_store().tickets()
        recorded = [r for r in rows if r.get("outcome")]
        return {
            "counts": counts,
            "vehicles": briefs,
            "outcomes": {
                "tickets": len(rows),
                "recorded": len(recorded),
                "confirmed": sum(1 for r in recorded if r["outcome"] == "confirmed"),
            },
        }

    @router.get("/vehicles/{vehicle_id}")
    def vehicle(vehicle_id: str) -> dict[str, Any]:
        return vehicle_detail(get_fleet(), vehicle_or_404(vehicle_id))

    @router.get("/threads/current")
    def current_thread(vehicle_id: str, request: Request) -> dict[str, Any] | None:
        b = browser(request)
        data = threads.get(b, vehicle_id) if b else None
        if not data:
            return None
        return {k: data[k] for k in ("thread_id", "session_id", "transcript", "sources", "pending")}

    @router.post("/chat")
    def chat(req: ChatIn, request: Request) -> StreamingResponse:
        rate_limit(request)
        v = vehicle_or_404(req.vehicle_id)
        b = browser(request) or secrets.token_hex(16)
        old = None if req.new_thread else threads.get(b, v.vehicle_id)
        session_id = req.session_id or (old or {}).get("session_id")
        if not session_id:
            raise HTTPException(422, "Выберите проверку.")
        if old and old.get("session_id") != session_id:
            old = None  # другая проверка — новый разговор
        thread = old or {
            "thread_id": secrets.token_hex(8),
            "session_id": session_id,
            "state": None,
            "transcript": [],
            "sources": [],
            "pending": None,
            "verdict_sent": False,
        }

        def events() -> Iterator[str]:
            yield _sse({"type": "thread", "thread_id": thread["thread_id"]})
            try:
                ag = get_agent()
                conv = conv_state.load(thread["state"], get_fleet()) if thread["state"] else None
                if conv is None:
                    conv = ag.start(v.vehicle_id, session_id)
                reply = ag.ask(conv, req.message, req.level)
            except ServiceError as exc:
                yield _sse({"type": "error", "message": exc.message})
                yield _sse({"type": "done", "reason": "error"})
                return
            tools, thread["verdict_sent"] = tool_events(reply, conv, bool(thread.get("verdict_sent")))
            for e in tools:
                yield _sse(e)
            sources = source_items(reply, conv)
            if sources:
                yield _sse({"type": "sources", "items": sources})
            text = to_handles(reply.text)
            yield _sse({"type": "text", "text": text, "round": 1})
            ver = verification(reply, text)
            yield _sse(ver)
            pending = ticket_pending(conv)
            if pending is not None:
                yield _sse(pending)
            usage = usage_events(reply)
            for u in usage:
                yield _sse(u)
            # Наши функции, которых пока нет в компонентах v2: интерфейс незнакомые события пропускает (#52 п. 3).
            pp = passport.build(reply.trace, question=req.message, notes=reply.notes, level=req.level)
            yield _sse({"type": "passport", **pp})
            spoken = speech_for(reply.text, conv.sources)
            yield _sse(
                {
                    "type": "speech",
                    "text": spoken.text,
                    "sig": conv_state.sign_text(spoken.text),
                    "url": "/api/voice/speak",
                }
            )
            known = {s["handle"] for s in thread["sources"]}
            thread["sources"] += [s for s in sources if s["handle"] not in known]
            blocks = [e["block"] for e in tools if e.get("type") == "tool_result" and e.get("block")]
            thread["transcript"] += [
                {"role": "user", "text": req.message},
                {
                    "role": "assistant",
                    "text": text,
                    "blocks": blocks,
                    "tools": [
                        {"id": e["id"], "name": e["name"], "label": e.get("label"), "ok": True}
                        for e in tools
                        if e["type"] == "tool_started"
                    ],
                    "usage": usage,
                    "verification": {k: ver[k] for k in ver if k not in ("type", "text")},
                    "passport": pp,
                },
            ]
            thread["pending"] = {k: pending[k] for k in pending if k != "type"} if pending else None
            thread["state"] = conv_state.dump(conv)
            threads.put(b, v.vehicle_id, thread)
            yield _sse({"type": "done", "reason": "end"})

        resp = StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})
        if browser(request) is None:
            resp.set_cookie(
                COOKIE, b, max_age=30 * 86400, httponly=True, samesite="lax", secure=request.url.scheme == "https"
            )
        return resp

    def thread_with_pending(request: Request, vehicle_id: str, pending_id: str) -> tuple[str, dict[str, Any]]:
        b = browser(request)
        data = threads.get(b, vehicle_id) if b else None
        if not data or not data.get("pending") or data["pending"]["pending_id"] != pending_id:
            raise HTTPException(409, "Черновик заявки устарел — попросите подготовить заявку заново.")
        return b or "", data

    @router.post("/tickets/{pending_id}/approve")
    def approve(pending_id: str, decision: TicketDecision, request: Request) -> dict[str, Any]:
        rate_limit(request)
        b, data = thread_with_pending(request, decision.vehicle_id, pending_id)
        pending = data["pending"]
        if pending["warning"] and not decision.warning_acknowledged:
            raise HTTPException(409, "Результат предварительный — отметьте, что поняли это.")
        if decision.urgency and decision.urgency != pending["payload"]["urgency"]:
            raise HTTPException(409, "Приоритет задаёт правило кода (D-6) — отправьте с предложенным.")
        ag = get_agent()
        conv = conv_state.load(data["state"], get_fleet())
        if conv.draft is None or conv.draft.fingerprint != pending_id:
            raise HTTPException(409, "Черновик заявки устарел — попросите подготовить заявку заново.")
        body = conv.draft.body.model_dump()
        ops = [body["operations"][i] for i in decision.keep_operations if 0 <= i < len(body["operations"])]
        parts = [body["spare_parts"][i] for i in decision.keep_spare_parts if 0 <= i < len(body["spare_parts"])]
        if not decision.keep_operations:
            ops = body["operations"]  # ничего не отмечено — механик подтверждает показанный состав целиком
            parts = body["spare_parts"] if not decision.keep_spare_parts else parts
        if not ops:
            raise HTTPException(409, "В заявке должна остаться хотя бы одна работа.")
        if ops != body["operations"] or parts != body["spare_parts"]:
            # механик убрал лишнее из показанного состава (только убрать, не добавить): новый отпечаток —
            # и все проверки confirm_ticket заново (статус, совместимость, ссылки, повтор)
            from service.agent import TicketDraft, fingerprint

            new_body = TicketRequest.model_validate({**body, "operations": ops, "spare_parts": parts})
            conv.draft = TicketDraft(
                body=new_body, urgency_reason=conv.draft.urgency_reason, fingerprint=fingerprint(new_body)
            )
        try:
            resp = ag.confirm_ticket(conv, conv.draft.fingerprint)
        except ServiceError as exc:
            raise HTTPException(exc.http_status, exc.message) from exc
        store = get_store()
        store.set_urgency_proposed(resp.ticket_id, pending["payload"]["urgency"])
        row = next(r for r in store.tickets(decision.vehicle_id) if r["ticket_id"] == resp.ticket_id)
        view = ticket_view(row)
        data["transcript"].append({"role": "ticket", "ticket": view})
        data["pending"] = None
        data["state"] = conv_state.dump(conv)
        threads.put(b, decision.vehicle_id, data)
        return view

    @router.post("/tickets/{pending_id}/reject", status_code=204)
    def reject(pending_id: str, decision: TicketDecision, request: Request) -> Response:
        b, data = thread_with_pending(request, decision.vehicle_id, pending_id)
        conv = conv_state.load(data["state"], get_fleet())
        conv.draft = None
        data["pending"] = None
        data["state"] = conv_state.dump(conv)
        threads.put(b, decision.vehicle_id, data)
        return Response(status_code=204)

    @router.get("/vehicles/{vehicle_id}/pages/{manual_id}/{page}")
    def manual_page(vehicle_id: str, manual_id: str, page: int, quote: str | None = None) -> dict[str, Any]:
        """Страница руководства для просмотрщика: только руководства двигателя этой машины (правило 3)."""
        v = vehicle_or_404(vehicle_id)
        doc = next((d for d in documents_for_engine(v.engine_model) if d.doc_id == manual_id), None)
        if doc is None:
            raise HTTPException(404, "Это руководство не относится к двигателю машины.")
        images = get_pages() if get_pages else None
        pages = doc.pages or (images.pages(manual_id) if images else 0)
        if not 1 <= page <= max(pages, 1) or (pages and page > pages):
            raise HTTPException(404, f"В руководстве нет страницы {page}.")
        searcher = getattr(get_agent(), "searcher", None)
        page_text = getattr(searcher, "page_text", None)
        text = (page_text(manual_id, page) if page_text else None) or ""
        image = f"/manuals/{manual_id}/page/{page}.webp" if images and images.available(manual_id, page) else None
        return {
            "manual_id": manual_id,
            "short": short_name(manual_id, doc.designation),
            "designation": doc.designation,
            "page": page,
            "pages": pages,
            "text": text,
            "image": image,
            "marks": [],  # подсветка строки — следующий шаг (приём Никиты page_marks)
            "focus": None,
        }

    @router.post("/transcribe")
    async def transcribe(request: Request) -> dict[str, Any]:
        """Голос: WAV 16 кГц моно (интерфейс v2 пишет его через WebAudio) → текст для поля ввода."""
        from service.voice import NOT_HEARD, pcm_from_wav, stt_cost_rub, timed

        rate_limit(request)
        if get_speech is None:
            raise HTTPException(503, "Голос сейчас недоступен — задайте вопрос текстом.")
        body = await request.body()
        try:
            pcm, seconds = pcm_from_wav(body)
            text, ms = timed(get_speech().recognize, pcm)
        except ServiceError as exc:
            raise HTTPException(exc.http_status, exc.message) from exc
        get_store().log_voice("stt", round(seconds, 2), stt_cost_rub(seconds), ms)
        if not text:
            raise HTTPException(422, NOT_HEARD)
        return {"text": text}

    @router.get("/vehicles/{vehicle_id}/tickets")
    def tickets(vehicle_id: str) -> list[dict[str, Any]]:
        vehicle_or_404(vehicle_id)
        return [ticket_view(r) for r in get_store().tickets(vehicle_id)]

    @router.post("/tickets/{ticket_pk}/outcome")
    def outcome(ticket_pk: int, body: OutcomeIn) -> dict[str, Any]:
        store = get_store()
        if store.ticket(ticket_pk) is None:
            raise HTTPException(404, "Заявка не найдена.")
        store.set_outcome(ticket_pk, body.outcome, body.note)
        row = store.ticket(ticket_pk)
        if row is None:  # удалена между запросами
            raise HTTPException(404, "Заявка не найдена.")
        return ticket_view(row)

    @router.get("/outcomes.csv")
    def outcomes_csv() -> Response:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(
            [
                "ticket_id",
                "vehicle_id",
                "session_id",
                "anomaly_type",
                "urgency",
                "outcome",
                "outcome_note",
                "created_at",
            ]
        )
        for r in get_store().tickets():
            created = datetime.fromtimestamp(r["ts"], UTC).isoformat()
            w.writerow(
                [
                    r["ticket_id"],
                    r["vehicle_id"],
                    r["session_id"],
                    r["anomaly_type"],
                    r["urgency"],
                    r.get("outcome") or "",
                    r.get("outcome_note") or "",
                    created,
                ]
            )
        return Response(
            content="﻿" + buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="outcomes.csv"'},
        )

    return router


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
