"""Паспорт запроса (issue #31): значок «?» у ответа — что делал помощник, с какими данными и сколько это стоило.

Собирается сервером из трассы агента, без нового учёта: вопрос (и голос), инструменты с параметрами, обращения к
руководству (что ушло в модель и использовано ли в ответе), вызовы модели (токены, ₽), речь, сработавшие правила
кода, итог по участкам. Системного промпта здесь нет. Сумма по модели — та же, что в журнале расходов (`llm_calls`).

Копия без персональных данных (без текста вопроса и ответа, без запросов поиска и номера машины) пишется в бакет
`logs/<дата>/passport/<request_id>.json` через `put` журнала стенда (#27, `service.stand_log`) — за флагом
`PASSPORT_LOG=bucket`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from service.agent import MSK, approx_tokens

log = logging.getLogger(__name__)

TOOL_TITLES = {
    "get_diagnosis": "Результат проверки",
    "vehicle_history": "История машины",
    "search_manual": "Поиск по руководству",
    "draft_ticket": "Черновик заявки",
    "fleet_summary": "Сводка парка",
}


def _price(key: str) -> float:
    from service.store import ex_vat, price_table

    row = price_table()["other"].get(key) or {}
    value = row.get("value")
    return ex_vat(float(value), bool(row.get("vat_included"))) if value is not None else 0.0


def _rules(rules: dict[str, Any], notes: list[str]) -> list[str]:
    out = []
    if rules.get("answer_cache"):
        out.append("Ответ из кэша: тот же вопрос, двигатель и результат проверки — модель не вызывалась (0 токенов).")
    if rules.get("prompt_leak"):
        out.append("Попытка вывести служебные настройки — ответ заменён отказом.")
    if rules.get("numbers_dropped"):
        out.append(f"Убрано предложений с цифрами не из руководства: {rules['numbers_dropped']}.")
    if rules.get("opinions_marked"):
        out.append(f"Помечено выводов без источника (рассуждение, не руководство): {rules['opinions_marked']}.")
    if rules.get("ungrounded"):
        out.append("В ответе нет ссылки на руководство — показана плашка.")
    if rules.get("code_compatible") is False:
        out.append("Код неисправности не подходит к двигателю — заявка невозможна.")
    if rules.get("card_status") == "check_failed":
        out.append("Проверка не удалась — выводов о двигателе нет, заявки нет.")
    if not out:
        out.append("Ответ прошёл проверки кода без правок.")
    return out + [f"Плашка механику: {n}" for n in notes if n not in out]


WHY_SEARCH = "найдено поиском по руководству"
NOT_CITED = "модель не сослалась на эту страницу"
WITHDRAWN_WHY = {
    "unverified": "цифры не подтвердились на этой странице — утверждение снято",
    "uncited": "у числа не было ссылки на страницу — утверждение снято",
    "other_row": "число со страницы относится к другой строке таблицы — утверждение снято",
}
PART_WORDS = {
    "instructions": "инструкция агента",
    "tool_results": "страницы руководства и карточка проверки",
    "dialog": "вопрос и разговор",
    "service": "служебные вызовы (план поиска, перевод)",
}


def _num(n: float) -> str:
    """5957 → «5 957»: разряды неразрывным пробелом, как в интерфейсе."""
    return f"{round(n):,}".replace(",", "\u00a0")


def _why_out(ref: str, withdrawn: list[dict[str, Any]]) -> str:
    """Почему страница, ушедшая в модель, не пошла в ответ: то, что знает проверка цифр (guard)."""
    for w in withdrawn:
        if ref in (w.get("handles") or []):
            key = "other_row" if w.get("reason") == "other_row" else str(w.get("state") or "unverified")
            return WITHDRAWN_WHY.get(key, WITHDRAWN_WHY["unverified"])
    return NOT_CITED


def token_parts(steps: list[dict[str, Any]]) -> dict[str, int]:
    """Вход модели по частям, в токенах провайдера: у каждого вызова оценка частей (≈ 4 символа на токен)
    приводится к его настоящему `tokens_in`; вызовы без разбивки (план поиска, перевод) — «служебные»."""
    out = {"instructions": 0, "tool_results": 0, "dialog": 0, "service": 0}
    for st in steps:
        if st.get("kind") != "llm":
            continue
        real = int(st.get("tokens_in") or 0)
        parts = st.get("parts") or {}
        approx = sum(parts.values())
        if not parts or not approx:
            out["service"] += real
            continue
        shares = {k: real * v / approx for k, v in parts.items()}
        rounded = {k: int(v) for k, v in shares.items()}
        rounded["dialog"] = rounded.get("dialog", 0) + real - sum(rounded.values())  # сумма — ровно tokens_in
        for k, v in rounded.items():
            out[k] = out.get(k, 0) + v
    return out


def explain(
    total: dict[str, Any], parts: dict[str, int], cached_cheaper: float, from_cache: bool = False
) -> dict[str, str]:
    """Паспорт простыми словами (Валерий, 27.11: «всё понятно с листа»): из чего вход, что из кэша, что лишнее,
    сколько стоило."""
    tin = int(total.get("tokens_in") or 0)
    pieces = [f"{PART_WORDS[k]} {_num(v)}" for k, v in parts.items() if v]
    lines = {
        "cost": f"{total['total_rub']:.2f} ₽ · {total['ms'] / 1000:.1f} с".replace(".", ","),
        "tokens": f"{_num(tin)} токенов на входе" + (f" ≈ {' + '.join(pieces)}" if pieces else ""),
    }
    if from_cache and not tin:
        lines["tokens"] = "ответ из сохранённого: тот же вопрос по той же проверке — модель не вызывалась, 0 токенов"
    cached = int(total.get("tokens_cached") or 0)
    if cached:
        cheaper = f", дешевле в {round(cached_cheaper)} раз" if cached_cheaper > 1 else ""
        lines["cached"] = f"из них {_num(cached)} повторно использовано (кэш провайдера) — почти бесплатно{cheaper}"
    sent, unused = int(total.get("fragments_tokens") or 0), int(total.get("unused_tokens") or 0)
    if sent and not (from_cache and not tin):  # из кэша страницы не оплачивались
        lines["unused"] = (
            f"{round(100 * unused / sent)} % страниц оплачено, но не понадобилось "
            f"({_num(unused)} из {_num(sent)} токенов руководства)"
        )
    return lines


def _cached_cheaper(provider: str | None) -> float:
    """Во сколько раз токен из кэша дешевле обычного входа — по прайсу провайдера (DeepSeek: 0,3 / 0,006 = 50)."""
    if not provider:
        return 0.0
    try:
        from service.store import prices

        p = prices(provider)
        return p.tokens_in / p.tokens_cached if p.tokens_cached else 0.0
    except Exception:  # прайс — для подписи, его сбой паспорт не ломает
        return 0.0


def build(
    trace: dict[str, Any],
    *,
    question: str,
    notes: list[str] | None = None,
    by_voice: bool = False,
    stt: dict[str, Any] | None = None,
    speech_text: str = "",
    level: str | None = None,
    level_reason: str | None = None,
) -> dict[str, Any]:
    """Паспорт по разделам issue #31. `stt` — запись журнала голоса о распознавании этого вопроса."""
    steps = trace.get("steps") or []
    withdrawn = trace.get("withdrawn") or []
    # у каждой страницы — почему она в контексте и, если не пошла в ответ, почему
    fragments = {
        f["ref"]: {
            **f,
            "why_in": f.get("why") or WHY_SEARCH,
            "why_out": None if f.get("used") else _why_out(f["ref"], withdrawn),
        }
        for f in trace.get("fragments") or []
    }
    plan = trace.get("plan") or {}

    tools = [
        {
            "name": TOOL_TITLES.get(s.get("tool", ""), s.get("tool") or s.get("name", "")),
            "tool": s.get("tool") or s.get("name"),
            "by": "код" if s.get("by_code") else "модель",
            "params": s.get("params") or {},
            "ok": s.get("ok"),
            "ms": s.get("ms", 0),
            **({"refused": s["refused"]} if s.get("refused") else {}),
        }
        for s in steps
        if s.get("kind") == "tool"
    ]
    searches = []
    for s in steps:
        if s.get("kind") != "tool" or not s.get("search"):
            continue
        sr = s["search"]
        searches.append(
            {
                "by": "код" if s.get("by_code") else "модель",
                "engine": sr.get("engine"),
                "queries": [q for q in sr.get("queries") or [] if q],
                "found": sr.get("found", 0),
                "fragments": [fragments[r] for r in sr.get("refs") or [] if r in fragments],
            }
        )
    if not searches and fragments:  # ответ из кэша: поиска в этом запросе не было, фрагменты — из сохранённого ответа
        searches.append(
            {"by": "кэш", "engine": None, "queries": [], "found": len(fragments), "fragments": list(fragments.values())}
        )
    llm = [
        {
            "name": s.get("name"),
            "provider": trace.get("provider"),
            "tokens_in": s.get("tokens_in", 0),
            "tokens_cached": s.get("tokens_cached", 0),
            "tokens_out": s.get("tokens_out", 0),
            "ms": s.get("ms", 0),
            "cost_rub": s.get("cost_rub", 0.0),
        }
        for s in steps
        if s.get("kind") == "llm"
    ]

    sent = list(fragments.values())
    sent_tokens = sum(f["tokens"] for f in sent)
    unused_tokens = sum(f["tokens"] for f in sent if not f["used"])
    queries = [q for s in searches for q in s["queries"]]
    search_rub = sum(approx_tokens(q) for q in queries) * _price("embedding") / 1000
    stt_rub = float(stt["cost_rub"]) if stt else 0.0
    from service.voice import choose_tts_api, for_tts, tts_cost_rub

    tts_chars = len(for_tts(speech_text)) if by_voice else 0  # символы, уходящие в синтез
    tts_rub = tts_cost_rub(tts_chars, choose_tts_api(tts_chars)) if tts_chars else 0.0  # без кэша — оценка сверху
    model_rub = float(trace.get("cost_rub") or 0.0)
    parts = token_parts(steps)
    total = {
        "model_rub": round(model_rub, 4),
        "search_rub": round(search_rub, 5),
        "voice_rub": round(stt_rub + tts_rub, 4),
        "total_rub": round(model_rub + search_rub + stt_rub + tts_rub, 4),
        "tokens_in": trace.get("tokens_in", 0),
        "tokens_cached": trace.get("tokens_cached", 0),
        "tokens_out": trace.get("tokens_out", 0),
        "ms": sum(int(s.get("ms") or 0) for s in steps),
        "fragments_tokens": sent_tokens,
        "unused_tokens": unused_tokens,
        "unused_share": round(unused_tokens / sent_tokens, 2) if sent_tokens else 0.0,
        "tokens_parts": parts,
    }
    return {
        "request_id": trace.get("request_id"),
        "question": {
            "text": question,
            "by_voice": by_voice,
            "stt_seconds": float(stt["units"]) if stt else None,
            "lang": plan.get("lang", "ru"),
            "question_ru": plan.get("question_ru"),
            "level": level,
            "level_reason": level_reason,
        },
        "tools": tools,
        "searches": searches,
        "llm": llm,
        "voice": {
            "stt_seconds": float(stt["units"]) if stt else 0.0,
            "stt_rub": round(stt_rub, 4),
            "tts_chars": tts_chars,
            "tts_rub_estimate": round(tts_rub, 4),
        },
        "rules": _rules(trace.get("rules") or {}, notes or []),
        "total": total,
        # простыми словами, в порядке листа: откуда ответ (страницы с причинами — `searches[].fragments`),
        # сколько стоило, детали
        "explain": explain(
            total, parts, _cached_cheaper(trace.get("provider")), bool((trace.get("rules") or {}).get("answer_cache"))
        ),
    }


def for_card(card: Any, ml_ms: int) -> dict[str, Any]:
    """Паспорт карточки результата: модели нет — сервис диагностики, правила кода и матрица по руководству."""
    status = {"normal": "норма", "anomaly": "отклонение", "check_failed": "сбой проверки"}.get(card.status, card.status)
    rules = [f"Статус «{status}» — карточка по правилу кода, модель не вызывалась (0 токенов)."]
    if card.urgency:
        urgency = {"high": "высокая", "medium": "средняя", "low": "низкая"}.get(card.urgency, card.urgency)
        rules.append(f"Срочность «{urgency}» — правило кода: {card.urgency_reason}.")
    if not card.compatible:
        rules.append("Код неисправности не подходит к двигателю — заявка невозможна.")
    rules += [f"Плашка: {b}" for b in card.banners]
    diag = {"name": "Результат проверки", "tool": "get_diagnosis", "by": "код", "params": {}, "ok": True, "ms": ml_ms}
    tools = [diag]
    pages = []
    if card.manual:
        tools.append(
            {
                "name": "Матрица «код × двигатель»",
                "tool": "fault_matrix",
                "by": "код",
                "params": {},
                "ok": True,
                "ms": 0,
            }
        )
        m = card.manual
        pages = [
            {"manual": r["manual"], "pdf_page": r["pdf_page"], "what": r.get("what", "")}
            for r in (m.get("pages") or m.get("steps") or [])
        ]
    return {
        "request_id": None,
        "question": None,
        "tools": tools,
        "searches": [],
        "llm": [],
        "card_pages": pages,
        "voice": {"stt_seconds": 0.0, "stt_rub": 0.0, "tts_chars": 0, "tts_rub_estimate": 0.0},
        "rules": rules,
        "total": {
            "model_rub": 0.0,
            "search_rub": 0.0,
            "voice_rub": 0.0,
            "total_rub": 0.0,
            "tokens_in": 0,
            "tokens_cached": 0,
            "tokens_out": 0,
            "ms": ml_ms,
            "fragments_tokens": 0,
            "unused_tokens": 0,
            "unused_share": 0.0,
        },
    }


def redact(passport: dict[str, Any]) -> dict[str, Any]:
    """Копия для журнала: без текста вопроса, перевода, запросов поиска и параметров инструментов."""
    p: dict[str, Any] = json.loads(json.dumps(passport, ensure_ascii=False))
    q = p["question"]
    q["text"] = None
    q["question_ru"] = None
    for t in p["tools"]:
        t["params"] = sorted(t["params"])  # только имена параметров
        t.pop("refused", None)
    for s in p["searches"]:
        s["queries"] = len(s["queries"])
        for f in s.get("fragments") or []:  # в причине — запрос поиска («…»): его в журнал не пишем
            for k in ("why", "why_in"):
                if f.get(k):
                    f[k] = re.sub(r"«[^»]*»", "«…»", f[k])
    p["rules"] = [r for r in p["rules"] if not r.startswith("Плашка механику:")]
    return p


def key_for(request_id: str, ts: float) -> str:
    return f"logs/{datetime.fromtimestamp(ts, MSK):%Y-%m-%d}/passport/{request_id}.json"


def write(passport: dict[str, Any], ts: float, put: Callable[[str, bytes], None] | None) -> bool:
    """`PASSPORT_LOG=bucket` — копию без ПДн в бакет через `put` журнала стенда (#27), в фоне; иначе ничего.
    Сбой записи сервис не задевает."""
    if os.environ.get("PASSPORT_LOG", "off") != "bucket" or not passport.get("request_id") or put is None:
        return False
    body = json.dumps(redact(passport), ensure_ascii=False).encode("utf-8")
    key = key_for(str(passport["request_id"]), ts)

    def run() -> None:
        try:
            put(key, body)
        except Exception as exc:  # журнал не роняет сервис
            log.warning("паспорт %s не записан в бакет: %s", key, type(exc).__name__)

    threading.Thread(target=run, name="passport-log", daemon=True).start()
    return True
