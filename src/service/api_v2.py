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
import html
import io
import json
import logging
import os
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from service import conv_state, escalation, language, passport
from service.agent import LEVEL_WORD, Agent, AgentReply, Conversation, LevelChoice
from service.case_log import CaseLog, verify
from service.clients import NotFoundError, ServiceError, TicketRequest
from service.fleet import Fleet, Vehicle
from service.fleet_status import STATUS_LABEL, trend, vehicle_status
from service.manuals.catalog import DOCS_BY_ID, documents_for_engine
from service.parts_supplier import offers_for_parts
from service.store import Store
from service.verdict_policy import CONFIDENCE_LOW, URGENCY_ACTION, VerdictCard, heard_text, urgency_for
from service.voice import speech_for, speech_lang

log = logging.getLogger(__name__)

COOKIE = "dm_v2"
URGENCY_WORD = {"high": "высокий", "medium": "средний", "low": "низкий"}
URGENCY_LEVELS: tuple[Literal["high", "medium", "low"], ...] = ("high", "medium", "low")


def urgency_note(proposed: str, chosen: str, reason: str) -> str:
    """Строка о приоритете для заявки и паспорта: что предложило правило кода и что выбрал механик (#60)."""
    rule = f"по правилу кода — «{URGENCY_WORD[proposed]}» ({reason.rstrip('.')})"
    if chosen == proposed:
        return f"Приоритет {rule}; механик оставил его."
    return f"Приоритет выбран механиком: «{URGENCY_WORD[chosen]}»; {rule}."


STREAM_FAILED = "Ответ не получился из-за сбоя сервиса. Спросите ещё раз."
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


OUTCOME_BADGE = {
    "confirmed": "дефектовка: подтвердилось",
    "not_confirmed": "дефектовка: не подтвердилось",
    "other_fault": "дефектовка: другая неисправность",
}

Sent = dict[tuple[str, str], dict[str, Any]]


def sent_by_check(rows: list[dict[str, Any]]) -> Sent:
    """Отправленные заявки по (машина, проверка); у проверки с несколькими заявками — последняя."""
    out: Sent = {}
    for r in rows:  # новые сверху: первая встреченная — последняя по времени
        out.setdefault((r["vehicle_id"], r["session_id"]), r)
    return out


def ticket_badges(v: Vehicle, session_id: str | None, sent: Sent) -> list[dict[str, str]]:
    """«заявка создана» у машины, по последней проверке которой отправлена заявка; когда механик отметил исход
    дефектовки — сам исход. Заявка по более старой проверке о том, что машина показывает сейчас, не говорит."""
    row = sent.get((v.vehicle_id, session_id or ""))
    if row is None:
        return []
    return [{"code": "ticket_created", "label": OUTCOME_BADGE.get(row.get("outcome") or "", "заявка создана")}]


def _fleet_view(fleet: Fleet, v: Vehicle, sent: Sent | None = None) -> dict[str, Any]:
    st = vehicle_status(v, fleet.fault_titles)
    last = st.last
    urgency = None
    if last is not None and last.status == "anomaly" and st.status != "rerecord":
        urgency = urgency_for(last)[0]
    return {
        "status": None if st.status == "rerecord" else st.status,
        "label": STATUS_LABEL[st.status],
        "badges": ticket_badges(v, last.session_id if last else None, sent or {}),
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


def vehicle_brief(fleet: Fleet, v: Vehicle, sent: Sent | None = None) -> dict[str, Any]:
    sessions = sorted(v.sessions, key=lambda s: s.checked_at)
    return {
        **_vehicle(v),
        "sessions_count": len(sessions),
        "last_session": _session_brief(fleet, v, sessions[-1]) if sessions else None,
        "fleet": _fleet_view(fleet, v, sent),
    }


def vehicle_detail(fleet: Fleet, v: Vehicle, sent: Sent | None = None) -> dict[str, Any]:
    sessions = sorted(v.sessions, key=lambda s: s.checked_at)  # от старых к новым: интерфейс берёт последнюю
    manuals = [
        {"id": d.doc_id, "short": short_name(d.doc_id, d.designation), "title": d.designation, "pages": d.pages}
        for d in documents_for_engine(v.engine_model)
    ]
    return {
        **_vehicle(v),
        "sessions": [_session_brief(fleet, v, s) for s in sessions],
        "manuals": manuals,
        "fleet": _fleet_view(fleet, v, sent),
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

    def get(self, browser: str, vehicle_id: str, fresh: bool = False) -> dict[str, Any] | None:
        """`fresh` — из бакета, а не из памяти экземпляра (подтверждение заявки: нить мог изменить другой
        экземпляр — ревью 27.11). Бакет недоступен — копия в памяти."""
        k = self.key(browser, vehicle_id)
        with self._lock:
            if k in self._mem and not (fresh and self.bucket is not None):
                return self._mem[k]
        if self.bucket is None:
            return None
        try:
            data: dict[str, Any] = json.loads(self.bucket.get(f"v2/threads/{k}.json"))
        except Exception:  # нет нити или бакет недоступен
            with self._lock:
                return self._mem.get(k)
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
        # порог правила кода (verdict_policy.CONFIDENCE_LOW): ниже него вывод предварительный
        "confidence_threshold": CONFIDENCE_LOW,
        "confidence_word": None
        if confidence is None
        else ("высокая" if confidence >= 0.8 else "средняя" if confidence >= 0.6 else "низкая"),
        "signal_quality": diag.signal_quality,
        "quality_word": QUALITY_WORD.get(diag.signal_quality, diag.signal_quality),
        "urgency": urgency_view(card),
        "description": heard_text(diag.description),  # посторонний текст — только в foreign_text
        "foreign_text": getattr(card, "ml_injection", None),
        "model_version": diag.model_version,
    }


def contradiction_block(conv: Conversation, text: str) -> tuple[dict[str, Any] | None, str]:
    """Известное противоречие руководств (D-20, `contradictions`) — отдельным блоком для карточки v2, а текстовый
    блок, который вставил код, из ответа убирается, чтобы не было повтора. Блок ищется по строкам (заголовок,
    формулировки «- …», вывод с советом): после вставки код дописывает к строке страницы пометки вроде
    «(испытания на стенде)» — они сохраняются в `note`. Не нашёлся — текст как есть."""
    from service import contradictions

    if conv.contradiction is None:
        return None, text
    k, quotes = conv.contradiction
    lines = text.split("\n")
    head = f"{contradictions.HEADER} — {k.title}:"
    start = next((i for i, ln in enumerate(lines) if ln.strip() == head), None)
    if start is None:
        return None, text
    end = start + 1
    item_lines: list[str] = []
    while end < len(lines) and (lines[end].startswith("- ") or not lines[end].strip()):
        if lines[end].strip():
            item_lines.append(lines[end])
        end += 1
    last = lines[end] if end < len(lines) else ""
    if not last.startswith(contradictions.RULE) or not item_lines:
        return None, text
    # формулировок в тексте может быть меньше, чем цитат (guard снял строку): блок — по тем, что есть, а служебная
    # строка правила уходит из текста в блок (скрытая 27.11: «Безопасное правило: …» оставалось в ответе)
    by_line = []
    for line in item_lines:
        q = next((q for q in quotes if q.quote[:40] in line), None)
        if q is not None:
            by_line.append((q, line))
    if not by_line:
        return None, text
    # под правилом — строка эскалации (если очередь её дала)
    esc_at = end + 1 if end + 1 < len(lines) and contradictions.ESCALATION.match(lines[end + 1]) else None
    pages = {(q.doc, q.page) for q in quotes}
    refs = {(s.manual_id, s.pdf_page): s.ref for s in conv.sources.values() if (s.manual_id, s.pdf_page) in pages}
    items = []
    for q, line in by_line:
        ref = refs.get((q.doc, q.page))
        tail = line.split(f"[{ref}]", 1)[1] if ref and f"[{ref}]" in line else line.split("»", 1)[-1]
        items.append(
            {
                "handle": handle(ref) if ref else None,
                "label": q.label(),
                "quote": q.quote,
                "manual_id": q.doc,
                "pdf_page": q.page,
                "note": tail.strip().strip("()").strip() or None,
            }
        )
    conclusion = last  # безопасное правило — как в тексте (`contradictions.block`)
    line = lines[esc_at] if esc_at is not None else ""
    rest_lines = lines[:start] + lines[(esc_at if esc_at is not None else end) + 1 :]
    rest = "\n\n".join(p for p in (part.strip() for part in "\n".join(rest_lines).split("\n\n")) if p)
    block = {
        "kind": "contradiction",
        "title": k.title,
        "items": items,
        "conclusion": conclusion,
        # строка эскалации (Валерий, 27.11) — рядом с правилом, не вместо него
        "advice": line,  # прежнее поле — для текущего web/
        "escalation": escalation_view(line) if line else None,
    }
    return block, rest


_ESC_NUMBER = re.compile(r"\(№ (\d+)[);]")  # «(№ 3)» — передано, «(№ 3; источник: …)» — решено


def escalation_view(line: str) -> dict[str, Any]:
    m = _ESC_NUMBER.search(line)
    resolved = line.startswith("Решение по противоречию")
    return {"line": line, "number": int(m.group(1)) if m else None, "resolved": resolved}


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
    показывает «Найдено на странице». Нет числа из ответа на странице — пусто: ни колонтитул с номером страницы,
    ни первая строка фрагмента за «найденное число» не выдаются (стенд 27.11: ✓ у стр. 57 по колонтитулу «57»)."""
    from service.agent import numbers, page_body

    wanted: set[str] = set()
    for sentence in _SENTENCE.split(answer):
        if f"[{ref}]" in sentence:
            wanted |= numbers(sentence)
    lines = [ln.strip() for ln in page_body(source_text).splitlines() if ln.strip()]
    if wanted:
        best = max(lines, key=lambda ln: len(numbers(ln) & wanted), default="")
        if best and numbers(best) & wanted:
            return best[:240]
    return ""


# причина снятия guard → ключ `copy.thread.withdrawnWhy` интерфейса; неизвестный ключ интерфейс читает как «other»
WITHDRAWN_REASON = {"not_on_page": "not_on_page", "no_source": "no_source", "other_row": "other"}


def verification(reply: AgentReply, text: str) -> dict[str, Any]:
    """Что проверил код (`agent.guard`): страницы, на которые опирается ответ, и сколько снято. Наш guard не
    зачёркивает, а убирает предложение с цифрой не из фрагмента — оно считается снятым. `verified` — только
    страницы, на которых нашлось число из ответа (так их читает интерфейс: ✓ «на странице найдено число»)."""
    withdrawn = [
        {
            "text": to_handles(w["text"]),
            "state": w["state"],
            "missing": w.get("missing", []),
            "reason": WITHDRAWN_REASON.get(w.get("reason") or "", w.get("reason")),
            "handles": [handle(r) for r in w.get("handles", [])],
        }
        for w in reply.withdrawn
    ]
    lines = {handle(s["ref"]): quote_line(reply.text, s["ref"], s.get("quote") or "") for s in reply.sources}
    quotes = {h: line for h, line in lines.items() if line}
    verified = list(quotes)
    return {
        "type": "verification",
        "text": text,
        "verified": verified,
        "quotes": quotes,
        # снятые guard утверждения — по одному на пометку «Утверждение снято» в тексте, в том же порядке (как
        # WithdrawnClaim в web/src/api.ts); ссылки — метками S…, как в тексте
        "counts": {
            "verified": len(verified),
            "unverified": sum(1 for w in withdrawn if w["state"] == "unverified"),
            "uncited": sum(1 for w in withdrawn if w["state"] == "uncited"),
        },
        "withdrawn": withdrawn,
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


def early_verdict(ag: Agent, conv: Conversation) -> dict[str, Any] | None:
    """Карточка проверки до модели. Сервис диагностики недоступен — None: ошибку покажет ответ агента."""
    try:
        ag.verdict_card(conv)
    except ServiceError:
        return None
    return verdict_block(conv)


def verdict_events(block: dict[str, Any]) -> list[dict[str, Any]]:
    """Те же события, что у карточки из tool_events: интерфейс v2 их уже понимает."""
    return [
        {"type": "tool_started", "id": "verdict", "name": "get_diagnosis", "label": TOOL_LABEL["get_diagnosis"]},
        {"type": "tool_result", "id": "verdict", "name": "get_diagnosis", "ok": True, "block": block},
    ]


def manual_designations(conv: Conversation, code: str) -> dict[str, str]:
    """Строка запчасти черновика → обозначение из руководства (матрица, цитата сверена со страницей; D-29)."""
    from service.agent import _part_label
    from service.fault_matrix import cell_for

    cell = cell_for(code, conv.vehicle.engine_model)
    if cell is None or cell.status != "confirmed":
        return {}
    return {_part_label(r): r.designation for r in cell.spare_parts if r.designation}


def _line(conv: Conversation, text: str, manual_id: str | None, page: int | None) -> dict[str, Any]:
    """Работа или запчасть со своей страницей: руководство (id и обозначение, как в `references`), стр. PDF и
    метка S…, если страница есть среди найденного в разговоре. Страница неизвестна — поля пустые, строка есть."""
    src = next((s for s in conv.sources.values() if s.manual_id == manual_id and s.pdf_page == page), None)
    doc = DOCS_BY_ID.get(manual_id or "")
    designation = doc.designation if doc else (src.manual if src else None)
    if manual_id is None or page is None or designation is None:
        return {"text": text, "source": "", "manual_id": None, "manual": None, "short": None, "pdf_page": None,
                "quote": "", "scanned": False}  # fmt: skip
    return {
        "text": text,
        "source": handle(src.ref) if src else "",
        "manual_id": manual_id,
        "manual": designation,
        "short": short_name(manual_id, designation),
        "pdf_page": page,
        "quote": "",
        "scanned": False,
    }


def ticket_lines(conv: Conversation) -> dict[str, list[dict[str, Any]]] | None:
    """Каждая работа и запчасть черновика — со страницей, откуда она взята. В ТОиР это не уходит: в теле заявки
    работы — текстом, а страницы — общим списком `references` (контракт ТОиР). Работа — страница её ссылки R…
    (`TicketDraft.op_pages`); запчасть — строка перечня проверенной ячейки матрицы (`_part_label`) или ссылка [R…]
    в её тексте."""
    from service.agent import REF_MARK, _part_label
    from service.fault_matrix import cell_for

    d = conv.draft
    if d is None:
        return None
    body = d.body
    cell = cell_for(body.anomaly_type, conv.vehicle.engine_model)
    matrix = cell if cell is not None and cell.status == "confirmed" else None
    op_quote = {o.quote: (o.doc, o.page) for o in matrix.operations} if matrix else {}
    part_label = {_part_label(p): (p.doc, p.page) for p in matrix.spare_parts} if matrix else {}

    def by_ref(text: str) -> tuple[str | None, int | None]:
        marks = REF_MARK.findall(text)
        src = conv.sources.get(marks[0]) if marks else None
        return (src.manual_id, src.pdf_page) if src else (None, None)

    ops = []
    for i, text in enumerate(body.operations):
        if len(d.op_pages) == len(body.operations):
            manual, page = d.op_pages[i]  # обозначение руководства, как в references
            src = next((s for s in conv.sources.values() if s.manual == manual and s.pdf_page == page), None)
            ops.append(_line(conv, text, src.manual_id if src else None, page))
        else:  # черновик из состояния до op_pages: работа из матрицы — её страница
            ops.append(_line(conv, text, *op_quote.get(text, (None, None))))
    parts = [_line(conv, t, *(part_label.get(t) or by_ref(t))) for t in body.spare_parts]
    return {"operations": ops, "spare_parts": parts}


def parts_offers(conv: Conversation, body: dict[str, Any], parts: Any | None) -> dict[str, Any] | None:
    """Предложения поставщиков по запчастям черновика (`parts_offers`); нет запчастей или поставщика — None."""
    if parts is None or not body["spare_parts"]:
        return None
    try:
        return offers_for_parts(parts, body["spare_parts"], manual_designations(conv, body["anomaly_type"]))
    except Exception as exc:  # поставщики не мешают черновику заявки
        log.warning("предложения поставщиков не получены: %s", type(exc).__name__)
        return {"connected": True, "note": "Поставщики сейчас не ответили — повторите позже.", "items": []}


def ticket_pending(conv: Conversation, parts: Any | None = None) -> dict[str, Any] | None:
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
        # каждая работа и запчасть — со своей страницей (руководство, стр. PDF, метка S…); в ТОиР — только payload
        **(ticket_lines(conv) or {"operations": [], "spare_parts": []}),
        "urgency": {
            "level": level,
            "word": URGENCY_WORD[level],
            "action": URGENCY_ACTION[level],
            "reasons": [d.urgency_reason],
        },
        # Приоритет предлагает правило кода (D-6); механик может выбрать другой (решение Валерия, #60) —
        # выбор и предложенное правилом пишутся в заявку и паспорт (`urgency_note`).
        "urgency_choices": [
            {"level": u, "word": URGENCY_WORD[u], "action": URGENCY_ACTION[u], "proposed": u == level}
            for u in URGENCY_LEVELS
        ],
        "warning": warning,
        "parts_offers": parts_offers(conv, body, parts),
    }


def _commit() -> str:
    sha = os.environ.get("GIT_SHA", "").strip()
    return sha if sha and sha != "unknown" else "unknown"


def _index_version() -> str | None:
    from service import kb_store
    from service.manuals.index import index_dir

    try:
        return kb_store.installed_version(index_dir())
    except Exception:
        return None


def topic_of(question: str) -> str:
    """Тема обращения — первый вопрос нити, без ПДн и короче 80 знаков."""
    from service.agent import mask_pii

    q = " ".join(mask_pii(question).split())
    return q if len(q) <= 80 else q[:79].rstrip() + "…"


def answer_record(conv: Conversation, reply: AgentReply, question: str, text: str) -> dict[str, Any]:
    """Запись для рекламации об ответе: что спросили, что ответили, по каким страницам, чем и какой версией."""
    from service.agent import mask_pii

    models = sorted({str(s.get("name")) for s in reply.trace.get("steps") or [] if s.get("kind") == "llm"})
    card = conv.card
    return {
        "kind": "answer",
        "session_id": conv.session_id,
        "engine": conv.vehicle.engine_model,
        "verdict": {"status": card.status, "fault_code": card.fault_code} if card else None,
        "question": mask_pii(question),
        "answer": text,
        "pages": [
            {"handle": f"S{s['ref'][1:]}", "manual": s["manual"], "pdf_page": s["pdf_page"], "quote": s.get("quote")}
            for s in reply.sources
        ],
        "provider": reply.trace.get("provider"),
        "models": models,
        "index_version": _index_version(),
        "commit": _commit(),
        "level": getattr(reply, "level_used", None),
        "lang": reply.lang,
        "request_id": reply.trace.get("request_id"),
    }


def export_html(vehicle: Any, row: dict[str, Any], records: list[dict[str, Any]], check: tuple[bool, str]) -> str:
    """Выгрузка нити для печати (рекламация): шапка, проверка цепочки, записи по порядку."""
    E = html.escape
    ok, why = check
    out = [
        "<!doctype html><html lang=ru><meta charset=utf-8>",
        f"<title>Обращение {E(row['thread_id'])} — {E(vehicle.vehicle_id)}</title>",
        "<style>body{font:14px/1.45 system-ui,sans-serif;max-width:48rem;margin:1rem auto;padding:0 1rem}"
        "h1{font-size:1.3rem}.rec{border-top:1px solid #999;padding:.5rem 0}.meta{color:#555;font-size:.85rem}"
        "blockquote{margin:.3rem 0;padding:.2rem .6rem;border-left:3px solid #999}.bad{color:#b42318}"
        "@media print{a{color:inherit}}</style>",
        f"<h1>Обращение по машине {E(vehicle.vehicle_id)} · {E(vehicle.engine_model)}</h1>",
        f"<p>Нить {E(row['thread_id'])} · проверка {E(str(row.get('session_id') or '—'))} · "
        f"с {E(row.get('started_at', ''))} по {E(row.get('updated_at', ''))} (UTC) · "
        f"тема: {E(row.get('topic', ''))}</p>",
        f'<p class="{"" if ok else "bad"}"><b>Целостность записи:</b> {"✓" if ok else "✗"} {E(why)}</p>',
    ]
    for r in records:
        head = f"№{r['seq']} · {r.get('at', '')} UTC"
        if r.get("kind") == "ticket":
            out.append(f'<div class="rec"><b>{E(head)} · заявка {E(str(r.get("ticket_id")))}</b>')
            out.append(f"<p>{E(str(r.get('conclusion', '')))}</p>")
        else:
            out.append(f'<div class="rec"><b>{E(head)}</b><p><b>Вопрос:</b> {E(r.get("question", ""))}</p>')
            out.append(f"<p><b>Ответ:</b><br>{E(r.get('answer', '')).replace(chr(10), '<br>')}</p>")
            for pg in r.get("pages") or []:
                out.append(
                    f"<blockquote>[{E(pg['handle'])}] {E(pg['manual'])}, стр. PDF {pg['pdf_page']}: "
                    f"{E((pg.get('quote') or '')[:600])}</blockquote>"
                )
        out.append(
            f'<p class="meta">модель: {E(", ".join(r.get("models") or []) or "—")} ({E(str(r.get("provider")))}) · '
            f"индекс {E(str(r.get('index_version')))} · коммит {E(str(r.get('commit'))[:12])} · "
            f"sha256 {E(r['sha256'][:16])}…</p></div>"
        )
    return "".join(out) + "</html>"


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
        # работы и запчасти со страницами — как механик их отправил; заявка, сохранённая раньше, — null
        "lines": json.loads(row["lines"]) if row.get("lines") else None,
        "outcome": row.get("outcome"),
        "outcome_note": row.get("outcome_note"),
    }


# ---------- язык ответа ----------


def language_event(code: str) -> dict[str, Any]:
    """Язык ответа и что умеет голос на нём — для переключателя языка в интерфейсе."""
    lang = language.LANGS.get(code) or language.LANGS["ru"]
    return {
        "lang": lang.code,
        "name": lang.native,
        "voice_input": lang.stt is not None,
        "voice_output": lang.code == "ru" or lang.voice is not None,
    }


# ---------- маршруты ----------


class ChatIn(BaseModel):
    vehicle_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    new_thread: bool = False
    # уровень механика: auto — по вопросу, на каждый вопрос заново; novice | mechanic | master — выбор механика;
    # прежние expert («Опытный» → master) и steps («Пошагово» → novice) принимаются
    level: LevelChoice = "auto"
    # язык ответа, выбранный механиком: ru, uz, uz-cyrl, tg, kk, ky, en; нет или "auto" — язык вопроса
    lang: str | None = Field(default=None, max_length=10)


class TicketDecision(BaseModel):
    vehicle_id: str = Field(min_length=1)
    # None (поле не передано) — весь показанный состав; [] — механик снял всё (работы — отказ, запчасти — без них)
    keep_operations: list[int] | None = None
    keep_spare_parts: list[int] | None = None
    warning_acknowledged: bool = False
    urgency: Literal["low", "medium", "high"] | None = None


class EscalationSend(BaseModel):
    to: Literal["manufacturer", "support"]
    by: str = Field(min_length=1, max_length=120)  # кто отправил (главный механик / поддержка)
    text: str | None = Field(default=None, max_length=8000)  # свой текст; нет — черновик кода


class EscalationResolve(BaseModel):
    text: str = Field(min_length=1, max_length=4000)  # ответ завода / поддержки
    by: str = Field(min_length=1, max_length=120)  # кто зафиксировал
    source: Literal["manufacturer", "support", "chief_mechanic"] = "manufacturer"
    document: str | None = Field(default=None, max_length=500)  # документ-основание: письмо, извещение, редакция


class ResumeIn(BaseModel):
    vehicle_id: str = Field(min_length=1)


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
    get_marks: Callable[[], Any] | None = None,
    get_log_put: Callable[[], Callable[[str, bytes], None] | None] | None = None,
    get_parts: Callable[[], Any] | None = None,
    case_log: CaseLog | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v2")
    cases = case_log or CaseLog()

    def remember(vehicle_id: str, thread: dict[str, Any], record: dict[str, Any] | None, **row: Any) -> None:
        """Долгая сессия: нить целиком по номеру, строка в истории машины, запись для рекламации. Сбой бакета
        механику ответ не ломает — пишется в журнал."""
        try:
            cases.save_thread(thread["thread_id"], {**thread, "vehicle_id": vehicle_id})
            meta = cases.touch(vehicle_id, thread["thread_id"], session_id=thread.get("session_id"), **row)
            if record is not None:
                cases.append(vehicle_id, thread["thread_id"], record, start=int(meta.get("records") or 0) + 1)
        except Exception as exc:
            log.warning("история обращений не записана: %s", type(exc).__name__)

    def parts_source() -> Any | None:
        """Поставщики запчастей (`parts_supplier.from_env`); без них — поля `parts_offers` нет."""
        return get_parts() if get_parts is not None else None

    def log_put() -> Callable[[str, bytes], None] | None:
        """`put` журнала стенда для копии паспорта (#27, `PASSPORT_LOG=bucket`); без журнала — None."""
        return get_log_put() if get_log_put is not None else None

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
        sent = sent_by_check(get_store().tickets())
        return [vehicle_brief(f, v, sent) for v in f.vehicles]

    @router.get("/fleet")
    def fleet() -> dict[str, Any]:
        f = get_fleet()
        rows = get_store().tickets()  # один раз на запрос: на стенде — чтение из бакета
        sent = sent_by_check(rows)
        briefs = [vehicle_brief(f, v, sent) for v in f.vehicles]
        order = {"quarantine": 0, "attention": 1, None: 2, "normal": 3}
        briefs.sort(key=lambda b: (order.get(b["fleet"]["status"], 2), -(b["fleet"]["anomaly_score"] or 0)))
        counts: dict[str, int] = {"normal": 0, "attention": 0, "quarantine": 0, "no_valid_check": 0}
        for b in briefs:
            counts[b["fleet"]["status"] or "no_valid_check"] += 1
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
        v = vehicle_or_404(vehicle_id)
        return vehicle_detail(get_fleet(), v, sent_by_check(get_store().tickets(vehicle_id)))

    @router.get("/vehicles/{vehicle_id}/verdict")
    def verdict(vehicle_id: str, session_id: str) -> dict[str, Any]:
        """Карточка проверки отдельным быстрым запросом, без модели: стенд отдаёт поток чата только целиком,
        а карточка из полей ML и правил кода готова за доли секунды. Интерфейс показывает её до ответа."""
        v = vehicle_or_404(vehicle_id)
        if not any(s.session_id == session_id for s in v.sessions):
            raise HTTPException(404, f"Проверка {session_id} машины {v.vehicle_id} не найдена.")
        ag = get_agent()
        try:
            conv = ag.start(v.vehicle_id, session_id)
            ag.verdict_card(conv)
        except NotFoundError as exc:
            raise HTTPException(404, exc.message) from exc
        except ServiceError as exc:
            raise HTTPException(502, exc.message) from exc
        block = verdict_block(conv)
        if block is None:
            raise HTTPException(502, "Карточку проверки собрать не удалось.")
        return block

    @router.get("/languages")
    def languages() -> list[dict[str, Any]]:
        """Языки ответа для переключателя: текст — все; голос — где есть у SpeechKit."""
        return [language_event(code) for code in language.LANGS]

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
            """Любой сбой посреди ответа (ревью 27.11): механик получает понятную ошибку и done, нить сохранена
            с его вопросом — а не оборванный поток."""
            finished = False
            try:
                for chunk in answer():
                    finished = finished or chunk.startswith('data: {"type": "done"')
                    yield chunk
            except Exception:
                log.exception("ответ v2 оборвался")
                if finished:
                    return
                thread["transcript"] += [
                    {"role": "user", "text": req.message},
                    {"role": "assistant", "text": STREAM_FAILED, "blocks": [], "tools": [], "usage": []},
                ]
                try:
                    threads.put(b, v.vehicle_id, thread)
                finally:
                    yield _sse({"type": "error", "message": STREAM_FAILED})
                    yield _sse({"type": "done", "reason": "error"})

        def answer() -> Iterator[str]:
            yield _sse({"type": "thread", "thread_id": thread["thread_id"]})
            card: dict[str, Any] | None = None
            try:
                ag = get_agent()
                conv = conv_state.load(thread["state"], get_fleet()) if thread["state"] else None
                if conv is None:
                    conv = ag.start(v.vehicle_id, session_id)
                if not thread.get("verdict_sent"):
                    # Карточка — из полей ML и правил кода, до первого вызова модели: приходит первой и
                    # остаётся на экране, если модель потом упадёт или кончится лимит расходов.
                    card = early_verdict(ag, conv)
                    if card is not None:
                        thread["verdict_sent"] = True
                        for e in verdict_events(card):
                            yield _sse(e)
                reply = ag.ask(conv, req.message, req.level, req.lang, back_translate=False)
            except ServiceError as exc:
                if card is not None:  # карточка уже на экране — и в нити, с вопросом и ошибкой
                    thread["transcript"] += [
                        {"role": "user", "text": req.message},
                        {"role": "assistant", "text": exc.message, "blocks": [card], "tools": [], "usage": []},
                    ]
                    threads.put(b, v.vehicle_id, thread)
                yield _sse({"type": "error", "message": exc.message})
                yield _sse({"type": "done", "reason": "error"})
                return
            tools, thread["verdict_sent"] = tool_events(reply, conv, bool(thread.get("verdict_sent")))
            if card is not None:  # первый get_diagnosis ответа — та же карточка, что уже ушла: второй строки нет
                dup = next(
                    (e["id"] for e in tools if e["type"] == "tool_started" and e["name"] == "get_diagnosis"), None
                )
                tools = [e for e in tools if e["id"] != dup]
            for e in tools:
                yield _sse(e)
            if card is not None:
                tools = [*verdict_events(card), *tools]  # в нить — вместе с остальными блоками ответа
            sources = source_items(reply, conv)
            if sources:
                yield _sse({"type": "sources", "items": sources})
            contra, answer_text = contradiction_block(conv, reply.text)
            if contra is not None:  # блок без шага: в журнале действий его нет, на экране — под ответом
                yield _sse(
                    {
                        "type": "tool_result",
                        "id": "contradiction",
                        "name": "contradictions",
                        "ok": True,
                        "block": contra,
                    }
                )
            text = to_handles(answer_text)
            level_info = {
                "level_used": reply.level_used,
                "level_word": LEVEL_WORD[reply.level_used],  # type: ignore[index]
                "level_reason": reply.level_reason,
            }
            yield _sse({"type": "text", "text": text, "round": 1, **level_info})
            ver = verification(reply, text)
            yield _sse(ver)
            # «Показать по-русски» — вслед за ответом, механик его не ждёт; цифры проверены guard
            try:
                ag.add_back_translation(conv, reply)
            except ServiceError:
                pass
            back = to_handles(reply.back_translation) if reply.back_translation else None
            if back:
                yield _sse({"type": "back_translation", "text": back})
            pending = ticket_pending(conv, parts_source())
            if pending is not None:
                yield _sse(pending)
            usage = usage_events(reply)
            for u in usage:
                yield _sse(u)
            # Наши функции, которых пока нет в компонентах v2: интерфейс незнакомые события пропускает (#52 п. 3).
            pp = passport.build(
                reply.trace,
                question=req.message,
                notes=reply.notes,
                level=reply.level_used,
                level_reason=reply.level_reason,
            )
            passport.write(pp, time.time(), put=log_put())  # журнал стенда (#27), как у /api/chat
            yield _sse({"type": "passport", **pp})
            spoken = speech_for(reply.text, conv.sources, reply.lang)
            voice_lang = speech_lang(reply.lang)
            yield _sse({"type": "language", **language_event(reply.lang)})  # интерфейс незнакомое пропускает
            yield _sse(
                {
                    "type": "speech",
                    "text": spoken.text,
                    "sig": conv_state.sign_text(spoken.text),
                    "url": "/api/voice/speak",
                    "lang": voice_lang,
                }
            )
            known = {s["handle"] for s in thread["sources"]}
            thread["sources"] += [s for s in sources if s["handle"] not in known]
            blocks = [e["block"] for e in tools if e.get("type") == "tool_result" and e.get("block")]
            if contra is not None:
                blocks.append(contra)
            thread["transcript"] += [
                {"role": "user", "text": req.message},
                {
                    "role": "assistant",
                    "text": text,
                    **level_info,
                    "back_translation": back,
                    "blocks": blocks,
                    "tools": [
                        {"id": e["id"], "name": e["name"], "label": e.get("label"), "ok": True}
                        for e in tools
                        if e["type"] == "tool_started"
                    ],
                    "usage": usage,
                    "verification": {k: ver[k] for k in ver if k not in ("type", "text")},
                    "passport": pp,
                    "speech": {
                        "text": spoken.text,
                        "sig": conv_state.sign_text(spoken.text),
                        "url": "/api/voice/speak",
                        "lang": voice_lang,
                    },
                },
            ]
            thread["pending"] = {k: pending[k] for k in pending if k != "type"} if pending else None
            thread["state"] = conv_state.dump(conv)
            thread.setdefault("topic", topic_of(req.message))  # тема обращения — первый вопрос нити
            threads.put(b, v.vehicle_id, thread)
            remember(
                v.vehicle_id,
                thread,
                answer_record(conv, reply, req.message, text),
                topic=thread["topic"],
                status="ticket_pending" if pending else None,
            )
            yield _sse({"type": "done", "reason": "end"})

        resp = StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})
        if browser(request) is None:
            resp.set_cookie(
                COOKIE, b, max_age=30 * 86400, httponly=True, samesite="lax", secure=request.url.scheme == "https"
            )
        return resp

    def thread_with_pending(request: Request, vehicle_id: str, pending_id: str) -> tuple[str, dict[str, Any]]:
        b = browser(request)
        data = threads.get(b, vehicle_id, fresh=True) if b else None
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
        ag = get_agent()
        conv = conv_state.load(data["state"], get_fleet())
        if conv.draft is None or conv.draft.fingerprint != pending_id:
            raise HTTPException(409, "Черновик заявки устарел — попросите подготовить заявку заново.")
        body = conv.draft.body.model_dump()
        # поле не передано — показанный состав целиком; пустой список — механик снял всё (ревью 27.11: раньше
        # пустой список работ отправлял весь состав)
        keep_ops = range(len(body["operations"])) if decision.keep_operations is None else decision.keep_operations
        keep_parts = range(len(body["spare_parts"])) if decision.keep_spare_parts is None else decision.keep_spare_parts
        kept = list(dict.fromkeys(i for i in keep_ops if 0 <= i < len(body["operations"])))  # без повторов
        ops = [body["operations"][i] for i in kept]
        parts = [body["spare_parts"][i] for i in keep_parts if 0 <= i < len(body["spare_parts"])]
        if not ops:
            raise HTTPException(409, "В заявке должна остаться хотя бы одна работа. Отметьте работы и отправьте снова.")
        proposed = pending["payload"]["urgency"]
        chosen = decision.urgency or proposed
        note = urgency_note(proposed, chosen, conv.draft.urgency_reason)
        if ops != body["operations"] or parts != body["spare_parts"] or chosen != body["urgency"]:
            # механик убрал лишнее из показанного состава (только убрать, не добавить) или выбрал другой
            # приоритет (#60): новый отпечаток — и все проверки confirm_ticket заново (статус, совместимость,
            # ссылки, повтор). Другой приоритет записан в заключении: в ТОиР видно, что выбрал механик.
            from service.agent import TicketDraft, fingerprint

            conclusion = body["conclusion"] if chosen == proposed else f"{body['conclusion']} {note}"
            refs = body["references"]
            op_pages = conv.draft.op_pages
            if len(op_pages) == len(body["operations"]):  # страница убранной работы — тоже из заявки
                dropped = {op_pages[i] for i in range(len(op_pages)) if i not in kept} - {op_pages[i] for i in kept}
                refs = [r for r in refs if (r["manual"], r["pdf_page"]) not in dropped]
            new_body = TicketRequest.model_validate(
                {**body, "operations": ops, "spare_parts": parts, "urgency": chosen, "conclusion": conclusion,
                 "references": refs}
            )  # fmt: skip
            conv.draft = TicketDraft(
                body=new_body,
                urgency_reason=conv.draft.urgency_reason,
                fingerprint=fingerprint(new_body),
                tools=conv.draft.tools,
                op_pages=[op_pages[i] for i in kept] if len(op_pages) == len(body["operations"]) else [],
            )
        lines = ticket_lines(conv)  # до отправки: то, что уйдёт в ТОиР, со страницей каждой работы и запчасти
        try:
            resp = ag.confirm_ticket(conv, conv.draft.fingerprint)
        except ServiceError as exc:
            raise HTTPException(exc.http_status, exc.message) from exc
        store = get_store()
        store.set_urgency_proposed(resp.ticket_id, proposed)
        store.set_lines(resp.ticket_id, lines)
        row = next(r for r in store.tickets(decision.vehicle_id) if r["ticket_id"] == resp.ticket_id)
        view = ticket_view(row)
        view["urgency_note"] = note
        view["parts_offers"] = pending.get("parts_offers")  # предложения, показанные на листе заявки
        # паспорт ответа, предложившего заявку: строка о приоритете — и копия в журнал стенда (PASSPORT_LOG)
        turn = next((t for t in reversed(data["transcript"]) if t.get("role") == "assistant"), None)
        if turn and turn.get("passport"):
            turn["passport"]["rules"].append(f"Заявка {resp.ticket_id}. {note}")
            passport.write(turn["passport"], time.time(), put=log_put())
        data["transcript"].append({"role": "ticket", "ticket": view})
        ticket_rec = {
            "kind": "ticket",
            "session_id": conv.session_id,
            "ticket_id": resp.ticket_id,
            "conclusion": view["payload"].get("conclusion"),
            "payload": view["payload"],
            "commit": _commit(),
            "index_version": _index_version(),
        }
        data["pending"] = None
        data["state"] = conv_state.dump(conv)
        threads.put(b, decision.vehicle_id, data)
        remember(decision.vehicle_id, data, ticket_rec, status="ticket_sent", ticket_id=resp.ticket_id)
        return view

    # ---------- противоречия: очередь главного механика (эскалация) ----------

    def queue() -> Any:
        return get_agent().escalation

    def item_or_404(number: int) -> dict[str, Any]:
        item = queue().get(number)
        if item is None:
            raise HTTPException(404, f"Противоречия № {number} нет.")
        return dict(item)

    @router.get("/contradictions")
    def contradictions_queue(status: Literal["open", "sent", "resolved", "all"] = "open") -> list[dict[str, Any]]:
        """Очередь главного механика: что, двигатель, обе формулировки со страницами, сколько раз всплывало."""
        return [dict(i) for i in queue().items(status)]

    @router.get("/contradictions/journal")
    def contradictions_journal() -> list[dict[str, Any]]:
        """Журнал решений (только добавление): отправлено кому и когда, решение — кем, когда, на каком основании."""
        return list(queue().journal())

    @router.get("/contradictions/{number}")
    def contradiction_item(number: int) -> dict[str, Any]:
        return item_or_404(number)

    @router.get("/contradictions/{number}/letter")
    def contradiction_letter(number: int, to: Literal["manufacturer", "support"] = "manufacturer") -> dict[str, Any]:
        """Черновик обращения заводу-изготовителю или в поддержку — собран кодом; код его не отправляет."""
        return {"to": to, "text": queue().letter(item_or_404(number), to), "channel": escalation.channel()}

    @router.post("/contradictions/{number}/send")
    def contradiction_send(number: int, body: EscalationSend) -> dict[str, Any]:
        """Отметка «отправлено»: кому, кто, когда, текст обращения (письмо не отправляется — канал на пилоте)."""
        item_or_404(number)
        return dict(queue().send(number, body.to, body.by, body.text))

    @router.post("/contradictions/{number}/resolve")
    def contradiction_resolve(number: int, body: EscalationResolve) -> dict[str, Any]:
        """Ответ завода / поддержки: после него агент показывает решение рядом с обеими формулировками."""
        item_or_404(number)
        return dict(queue().resolve(number, body.text, body.by, body.source, body.document))

    # ---------- долгая сессия: история обращений, продолжение, выгрузка для рекламации ----------

    @router.get("/vehicles/{vehicle_id}/threads")
    def vehicle_threads(vehicle_id: str) -> list[dict[str, Any]]:
        """История обращений по машине (новые сверху): дата, проверка, тема, статус, число записей."""
        vehicle_or_404(vehicle_id)
        return [
            {
                "thread_id": r["thread_id"],
                "started_at": r.get("started_at"),
                "updated_at": r.get("updated_at"),
                "session_id": r.get("session_id"),
                "topic": r.get("topic"),
                "status": r.get("status") or "open",
                "ticket_id": r.get("ticket_id"),
                "records": r.get("records", 0),
            }
            for r in cases.threads(vehicle_id)
        ]

    @router.post("/threads/{thread_id}/resume")
    def resume_thread(thread_id: str, body: ResumeIn, request: Request) -> Response:
        """Продолжить нить (через час или через полгода, с любого телефона): она становится текущей у браузера."""
        v = vehicle_or_404(body.vehicle_id)
        row = cases.thread_row(v.vehicle_id, thread_id)
        data = cases.load_thread(thread_id) if row else None
        if not data or data.get("vehicle_id") != v.vehicle_id:
            raise HTTPException(404, "Обращение не найдено или срок хранения истёк.")
        data.pop("vehicle_id", None)
        b = browser(request) or secrets.token_hex(16)
        threads.put(b, v.vehicle_id, data)
        resp = JSONResponse({k: data.get(k) for k in ("thread_id", "session_id", "transcript", "sources", "pending")})
        if browser(request) != b:
            resp.set_cookie(
                COOKIE, b, max_age=30 * 86400, httponly=True, samesite="lax", secure=request.url.scheme == "https"
            )
        return resp

    @router.get("/vehicles/{vehicle_id}/threads/{thread_id}/export", response_model=None)
    def export_thread(vehicle_id: str, thread_id: str, format: Literal["json", "html"] = "json") -> Any:
        """Запись для рекламации: все записи нити по порядку и проверка цепочки (номера, хэши, пропуски)."""
        v = vehicle_or_404(vehicle_id)
        row = cases.thread_row(v.vehicle_id, thread_id)
        if row is None:
            raise HTTPException(404, "Обращение не найдено или срок хранения истёк.")
        records = cases.records(v.vehicle_id, thread_id)
        ok, why = verify(records)
        if ok and len(records) < int(row.get("records") or 0):
            ok, why = False, f"записей {len(records)}, а должно быть {row['records']} — часть отсутствует"
        if format == "html":
            return HTMLResponse(export_html(v, row, records, (ok, why)))
        return {
            "vehicle_id": v.vehicle_id,
            "engine": v.engine_model,
            "thread": row,
            "integrity": {"ok": ok, "detail": why},
            "retention_days": cases.retention_days,
            "records": records,
        }

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
        box = get_marks().mark(manual_id, page, (quote or "")[:400]) if (get_marks and image and quote) else None
        mark = (
            {"x": box[0], "y": box[1], "w": round(box[2] - box[0], 4), "h": round(box[3] - box[1], 4)} if box else None
        )
        return {
            "manual_id": manual_id,
            "short": short_name(manual_id, doc.designation),
            "designation": doc.designation,
            "page": page,
            "pages": pages,
            "text": text,
            "image": image,
            # строка цитаты на картинке (приём Никиты page_marks): только если на странице она одна
            "marks": [mark] if mark else [],
            "focus": mark,
        }

    @router.post("/transcribe")
    async def transcribe(request: Request, lang: str = "ru") -> dict[str, Any]:
        """Голос: WAV 16 кГц моно (интерфейс v2 пишет его через WebAudio) → текст для поля ввода.
        `?lang=uz|kk|en` — язык распознавания (выбор механика); по умолчанию и для tg/ky — русский."""
        from service.voice import NOT_HEARD, pcm_from_wav, stt_cost_rub, timed

        rate_limit(request)
        if get_speech is None:
            raise HTTPException(503, "Голос сейчас недоступен — задайте вопрос текстом.")
        body = await request.body()
        try:
            pcm, seconds = pcm_from_wav(body)
            text, ms = timed(get_speech().recognize, pcm, language.normalize(lang) or "ru")
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

    @router.get("/tickets")
    def ticket_register() -> list[dict[str, Any]]:
        """Реестр главного механика: все заявки парка, новые сверху — машина, проверка, неисправность, приоритет
        предложенный и выбранный, исход дефектовки, работы и запчасти со страницами. Без вызова модели."""
        fleet = get_fleet()
        out = []
        for row in get_store().tickets():
            view = ticket_view(row)
            v = fleet.vehicle(row["vehicle_id"])
            session = next((s for s in v.sessions if s.session_id == row["session_id"]), None) if v else None
            code = view["payload"]["anomaly_type"]
            out.append(
                {
                    **view,
                    "garage_no": v.garage_no if v else None,  # None: машины уже нет в парке
                    "vehicle_name": v.display_name if v else None,
                    "engine_model": v.engine_model if v else None,
                    "checked_at": session.checked_at if session else None,
                    "fault_title": fleet.fault_titles.get(code) or code,
                }
            )
        return out

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
