"""Прогон сценария видео на стенде /v2 перед каждым дублем (приём Никиты `make demo-check`, его docs/demo.md).

    make demo-check STAND=https://<стенд>/           — заявка доводится до листа, в ТОиР не уходит
    make demo-check STAND=… ARGS=--send-ticket      — и отправить её (номер TKT займёт место в ТОиР до дубля)

Делает те же запросы, что телефон (`/api/v2/chat`, страница, озвучка), и печатает таблицу
«шаг → ожидалось → получили → ✅/❌» и секунды ожидания. Код 0 и «готово к дублю» — только если всё ✅.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

STAND = "https://bbab8qkqhuhg3ere9dam.containers.yandexcloud.net/"
DIAG = "Получить результат диагностики"
TICKET = "Оформи заявку на дефектовку."


@dataclass
class Turn:
    events: list[dict[str, Any]]
    seconds: float

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("type") == kind]

    def one(self, kind: str) -> dict[str, Any] | None:
        found = self.of(kind)
        return found[-1] if found else None

    @property
    def verdict(self) -> dict[str, Any] | None:
        blocks = [e.get("block") or {} for e in self.of("tool_result")]
        return next((b for b in blocks if b.get("kind") == "verdict"), None)

    @property
    def text(self) -> str:
        t = self.one("text")
        return str((t or {}).get("text", ""))

    @property
    def verified(self) -> list[str]:
        return list((self.one("verification") or {}).get("verified") or [])

    @property
    def error(self) -> str | None:
        e = self.one("error")
        return e.get("message") if e else None


@dataclass
class Report:
    rows: list[tuple[str, str, str, bool, float | None]] = field(default_factory=list)

    def add(self, step: str, expected: str, got: str, ok: bool, seconds: float | None = None) -> bool:
        self.rows.append((step, expected, got, ok, seconds))
        print(f"{'✅' if ok else '❌'} {step}: {got}" + (f" ({seconds:.1f} с)" if seconds is not None else ""))
        return ok

    def table(self) -> str:
        out = ["| Шаг | Ожидалось | Получили | | с |", "|---|---|---|---|---|"]
        for step, exp, got, ok, sec in self.rows:
            cell = got.replace("|", "/").replace("\n", " ")
            out.append(f"| {step} | {exp} | {cell} | {'✅' if ok else '❌'} | {'' if sec is None else f'{sec:.1f}'} |")
        return "\n".join(out)


class Phone:
    """Один «телефон»: своя кука (нить на сервере привязана к браузеру), источники копятся по нити."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=httpx.Timeout(180, connect=20), follow_redirects=True)
        self.sources: dict[str, dict[str, Any]] = {}

    def ask(self, vehicle: str, message: str, session: str | None = None, new: bool = False) -> Turn:
        body = {"vehicle_id": vehicle, "message": message, "session_id": session, "new_thread": new, "level": "steps"}
        events: list[dict[str, Any]] = []
        t0 = time.monotonic()
        with self.http.stream("POST", f"{self.base}/api/v2/chat", json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[5:].strip()))
        turn = Turn(events, time.monotonic() - t0)
        for e in turn.of("sources"):
            for s in e.get("items") or []:
                self.sources[s["handle"]] = s
        return turn

    def marked_page(self, vehicle: str, turn: Turn) -> tuple[bool, str]:
        """Первый чип с ✓, у которого строка отмечена на картинке страницы (как в сценарии: «следующий чип»)."""
        quotes = (turn.one("verification") or {}).get("quotes") or {}
        tried: list[str] = []
        for h in turn.verified:
            s = self.sources.get(h)
            if not s or not s.get("manual_id"):
                continue
            r = self.http.get(
                f"{self.base}/api/v2/vehicles/{vehicle}/pages/{s['manual_id']}/{s['pdf_page']}",
                params={"quote": quotes.get(h) or ""},
            )
            view = r.json() if r.status_code == 200 else {}
            where = f"{s.get('chip') or s['manual_id']} стр. {s['pdf_page']}"
            if view.get("image") and view.get("marks"):
                img = self.http.get(f"{self.base}{view['image']}")
                if img.status_code == 200:
                    return True, f"{where}: картинка и рамка на строке" + (
                        f" (до неё: {', '.join(tried)})" if tried else ""
                    )
            tried.append(f"{where} — {'нет рамки' if view.get('image') else 'нет картинки'}")
        return False, "; ".join(tried) or "чипов с ✓ нет"

    def speak(self, turn: Turn) -> tuple[int, str]:
        sp = turn.one("speech")
        if not sp or not sp.get("text"):
            return 0, "нет фразы для озвучки"
        r = self.http.post(f"{self.base}/api/voice/speak", json={"text": sp["text"], "sig": sp["sig"]})
        return r.status_code, f"{r.status_code}, {len(r.content) // 1024} КБ, {r.headers.get('X-TTS', '?')}"


def run(base: str, send_ticket: bool) -> Report:
    rep = Report()
    ph = Phone(base)
    h = ph.http.get(f"{ph.base}/health").json()
    idx = h.get("manuals_index") or {}
    ok = h.get("status") == "ok" and bool(idx.get("present")) and bool(h.get("llm_key_present"))
    build = h.get("build") or {}
    got = (
        f"{h.get('status')}, коммит {build.get('git_sha_short', '—')} ({build.get('built_at') or 'время сборки —'}), "
        f"индекс {idx.get('version') or '—'} ({idx.get('fragments')}), {h.get('llm_provider')}"
    )
    rep.add("Стенд /health", "ok, индекс есть, ключ модели есть", got, ok)
    v2 = ph.http.get(f"{ph.base}/v2/")
    rep.add("Интерфейс /v2", "200", str(v2.status_code), v2.status_code == 200)

    # --- 1. Отклонение: B418HK98 / S-0009 ---
    car = "B418HK98"
    t = ph.ask(car, DIAG, "S-0009", new=True)
    v = t.verdict or {}
    got = f"{v.get('case')}, {v.get('fault_code')} {v.get('fault_title') or ''}".strip() if v else (t.error or "нет")
    rep.add("B418HK98: карточка", "отклонение, код и приоритет", got, v.get("case") == "anomaly", t.seconds)
    rep.add("B418HK98: объяснение", "текст со ссылкой ✓", f"{len(t.text)} знаков, ✓ {len(t.verified)}", bool(t.text))
    ok, got = ph.marked_page(car, t)
    rep.add("Чип → страница", "лист с рамкой на строке", got, ok)

    t = ph.ask(car, "Какой тепловой зазор клапанов?")
    rep.add(
        "Вопрос о клапанах",
        "ответ со ссылкой ✓",
        f"{len(t.text)} знаков, ✓ {len(t.verified)}",
        bool(t.verified),
        t.seconds,
    )
    ok_q, got = ph.marked_page(car, t)
    rep.add("Чип ответа → страница", "лист с рамкой на строке", got, ok_q)

    t = ph.ask(car, "Можно ли своим ходом перегнать на базу?")
    nothing = "в руководстве нет" in t.text.lower() or "в руководстве этого нет" in t.text.lower()
    rep.add(
        "«Своим ходом на базу?»",
        "ответ по руководству (✓) или «в руководстве нет»",
        f"{len(t.text)} знаков, ✓ {len(t.verified)}" + (", «нет в руководстве»" if nothing else ""),
        bool(t.text) and (bool(t.verified) or nothing),
        t.seconds,
    )
    code, got = ph.speak(t)
    rep.add("Озвучка ответа", "200, mp3", got, code == 200)

    t = ph.ask(car, TICKET)
    p = t.one("ticket_pending")
    refs = (p or {}).get("payload", {}).get("references") or []
    ops = (p or {}).get("operations") or []
    got = (
        f"работ {len(ops)}, ссылок {len(refs)}, приоритет {(p or {}).get('urgency', {}).get('word')}"
        if p
        else "листа нет"
    )
    rep.add("Лист заявки", "работы и ссылки, кнопка «Отправить»", got, bool(p and ops and refs), t.seconds)
    if p and send_ticket:
        r = ph.http.post(
            f"{ph.base}/api/v2/tickets/{p['pending_id']}/approve",
            json={
                "vehicle_id": car,
                "keep_operations": list(range(len(ops))),
                "keep_spare_parts": list(range(len(p.get("spare_parts") or []))),
                "warning_acknowledged": bool(p.get("warning")),
            },
        )
        tid = r.json().get("ticket_id") if r.status_code < 300 else r.text[:120]
        rep.add("Отправка в ТОиР", "номер TKT-…", f"{r.status_code} {tid}", r.status_code < 300 and bool(tid))
    elif p:
        rep.add("Отправка в ТОиР", "не отправляли (без --send-ticket)", "пропущено — номер не занят", True)

    # --- 2. Сбой записи + посторонний текст: H142OX78 / S-0113 ---
    car = "H142OX78"
    t = ph.ask(car, DIAG, "S-0113", new=True)
    v = t.verdict or {}
    rep.add(
        "H142OX78: карточка", "сбой записи (серая)", str(v.get("case") or t.error), v.get("case") == "failed", t.seconds
    )
    foreign = v.get("foreign_text")
    rep.add("Посторонний текст", "показан отдельно, не влияет", (foreign or "нет")[:80], bool(foreign))
    rep.add("Без руководства", "ни одного источника", f"источников {len(t.of('sources'))}", not t.of("sources"))
    t = ph.ask(car, TICKET)
    rep.add(
        "Заявка при сбое",
        "листа нет",
        "лист есть" if t.one("ticket_pending") else "листа нет",
        not t.one("ticket_pending"),
    )

    # --- 3. Подача бензина на дизеле: M260EH47 / S-0079 ---
    car = "M260EH47"
    t = ph.ask(car, DIAG, "S-0079", new=True)
    v = t.verdict or {}
    rep.add(
        "M260EH47: карточка",
        "«узла нет»: результат не подходит двигателю",
        f"{v.get('case')}: {v.get('headline')}" if v else str(t.error),
        v.get("case") == "mismatch",
        t.seconds,
    )
    t = ph.ask(car, TICKET)
    rep.add(
        "Заявка при несовместимости",
        "листа нет",
        "лист есть" if t.one("ticket_pending") else "листа нет",
        not t.one("ticket_pending"),
    )
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demo_check")
    ap.add_argument("stand", nargs="?", default=STAND)
    ap.add_argument("--send-ticket", action="store_true", help="отправить заявку в ТОиР (займёт номер TKT)")
    ap.add_argument("--out", help="записать таблицу в файл (markdown)")
    args = ap.parse_args(argv)
    t0 = time.monotonic()
    try:
        rep = run(args.stand, args.send_ticket)
    except httpx.HTTPError as exc:
        print(f"❌ стенд не ответил: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    ok = all(r[3] for r in rep.rows)
    waits = sum(r[4] or 0 for r in rep.rows)
    verdict = "готово к дублю" if ok else "НЕ готово к дублю"
    total = time.monotonic() - t0
    summary = f"\n{rep.table()}\n\nОжидание модели и сервера: {waits:.0f} с, весь прогон {total:.0f} с. **{verdict}**"
    print(summary)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(f"# demo-check — {args.stand}\n{summary}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
