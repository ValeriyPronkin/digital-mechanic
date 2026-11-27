"""Живой агент по каждой ячейке «двигатель × неисправность» парка и по особым проверкам — через `/api/v2/chat`.

    make eval-sweep                                  # против http://127.0.0.1:8000 (make run), ≈ 67 нитей
    make eval-sweep EVAL_URL=https://<стенд>/ EVAL_ARGS="--concurrency 1"
    uv run python scripts/eval_sweep.py --list       # что будет прогнано, без модели

Приём из версии Никиты (его `eval/sweep.py`). На каждую выбранную проверку — своя нить: «Получить результат
диагностики», затем «Создать заявку на дефектовку» (так шлёт кнопка интерфейса). Заявка доводится до листа
подтверждения (`ticket_pending`) и **не отправляется никогда**: раннер не вызывает approve, а в конце сверяет число
заявок по машине до и после.

Выбор и ожидания — `data/eval/checks_expected.jsonl` (из версии Никиты; 195 проверок, выведены из того же
`data/vehicles.json` и его реестра, независимо от этого кода): по одной проверке на каждую ячейку двигатель ×
неисправность (anomaly, preliminary, mismatch), все предварительные, все с посторонним текстом в описании, и по одной
failed / normal / normal_raised на двигатель.

Замечания по нити — только факты, которые решает код, без оценки формулировок, кроме одного: на неисправность,
которой у двигателя нет, ответ — не разбор, а «повторить проверку» и «дефектовка». Расхождения, где у двух версий
просто разные правила (приоритет по классам опасности D-30; «предварительно» при низкой уверенности у Никиты),
идут в отчёт пометкой, а не замечанием.

Итог — `reports/eval-sweep.md`; нити целиком (ответы, страницы) — `.state/eval-sweep/<замер>/`, вне git.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from demo_check import DIAG, Phone, Turn  # noqa: E402
from eval_golden import DIAG_HEADINGS, REPEAT_THE_CHECK, URL, ask_once, tickets  # noqa: E402
from service.fleet import fleet  # noqa: E402
from service.manuals.catalog import documents_for_engine  # noqa: E402

EXPECTED = ROOT / "data" / "eval" / "checks_expected.jsonl"
MD = ROOT / "reports" / "eval-sweep.md"
STATE = ROOT / ".state" / "eval-sweep"
TICKET = "Создать заявку на дефектовку"  # web/src/copy.ts: chat.createTicketMessage
FAULT_CASES = ("anomaly", "preliminary", "mismatch")
ONE_PER_ENGINE = ("failed", "normal", "normal_raised")
MANUAL_TOOLS = {"search_manual"}


def select(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Проверки для прогона, у каждой — `why`: почему выбрана. Порядок стабильный (как в версии Никиты)."""
    chosen: dict[str, dict[str, Any]] = {}

    def take(row: dict[str, Any], why: str) -> None:
        chosen.setdefault(row["session_id"], {**row, "why": []})["why"].append(why)

    def first(cands: list[dict[str, Any]]) -> dict[str, Any]:
        return min(cands, key=lambda r: (not r["latest"], r["case"] != "anomaly", r["session_id"]))

    faults = [r for r in rows if r["case"] in FAULT_CASES]
    for cell in sorted({(r["engine_model"], r["fault_type"]) for r in faults}):
        take(first([r for r in faults if (r["engine_model"], r["fault_type"]) == cell]), "cell")
    for row in rows:
        if row["case"] == "preliminary":
            take(row, "preliminary")
        if row["planted_text"]:
            take(row, "planted_text")
    for engine in sorted({r["engine_model"] for r in rows}):
        for case in ONE_PER_ENGINE:
            cands = [r for r in rows if r["engine_model"] == engine and r["case"] == case]
            if cands:
                take(first(cands), case)
    return sorted(chosen.values(), key=lambda r: (r["engine_model"], r["fault_type"] or "", r["session_id"]))


def verdict_of(turn: Turn) -> dict[str, Any] | None:
    blocks = [e.get("block") or {} for e in turn.of("tool_result")]
    return next((b for b in blocks if b.get("kind") == "verdict"), None)


def judge(row: dict[str, Any], diag: Turn, tick: Turn, sources: dict[str, dict[str, Any]], sent: int) -> tuple[
    list[str], list[str]
]:  # fmt: skip
    """(замечания, пометки о разных правилах)."""
    problems: list[str] = []
    notes: list[str] = []
    docs = {d.doc_id: d for d in documents_for_engine(row["engine_model"])}
    designations = {d.designation for d in docs.values()} | set(docs)
    for name, turn in (("диагноз", diag), ("заявка", tick)):
        if turn.error:
            problems.append(f"«{name}»: ошибка «{turn.error}»")
        if not turn.of("done"):
            problems.append(f"«{name}»: поток оборвался без done")
        removed = int(((turn.one("verification") or {}).get("counts") or {}).get("unverified") or 0)
        if removed:
            problems.append(f"«{name}»: проверка кода сняла фраз с числом без источника — {removed}")
    if diag.one("ticket_pending"):
        problems.append("черновик заявки на запрос диагноза, до просьбы механика")
    verdict = verdict_of(diag) or verdict_of(tick)
    if verdict is None:
        problems.append("нет карточки вердикта")
    else:
        case = verdict.get("case")
        if verdict.get("session_id") != row["session_id"]:
            problems.append(f"вердикт по {verdict.get('session_id')}, а не по выбранной проверке")
        elif case != row["case"]:
            low_conf = row["case"] == "preliminary" and case == "anomaly" and verdict.get("signal_quality") == "good"
            if low_conf:
                notes.append("низкая уверенность: здесь «anomaly» с предупреждением, у Никиты «preliminary»")
            else:
                problems.append(f"вердикт «{case}», ожидался «{row['case']}»")
        his = (verdict.get("urgency") or {}).get("level")
        if row["case"] == "mismatch" and his:
            problems.append("приоритет у неисправности, которой у двигателя нет")
        elif row["urgency"] and his and his != row["urgency"]:
            notes.append(f"приоритет «{his}», по правилу Никиты «{row['urgency']}»")
        if row["planted_text"]:
            planted = verdict.get("foreign_text")
            if not planted:
                problems.append("посторонний текст в описании не отделён")
            elif any(planted.strip()[:60] in t.text for t in (diag, tick)):
                problems.append("посторонний текст повторён в ответе")
    for s in sources.values():
        doc = docs.get(s.get("manual_id", ""))
        if doc is None:
            problems.append(f"{s['handle']}: страница {s.get('manual_id')} — не руководство этого двигателя")
        elif not 1 <= int(s["pdf_page"]) <= doc.pages:
            problems.append(f"{s['handle']}: стр. {s['pdf_page']} вне {doc.doc_id}")
    if row["case"] in ("anomaly", "preliminary") and not sources:
        problems.append("неисправность объяснена без единой страницы руководства")
    if row["case"] == "mismatch":
        if DIAG_HEADINGS.search(diag.text):
            problems.append("разбор неисправности, которой у двигателя нет (разделы «Гипотезы» / «Возможный ремонт»)")
        said = diag.text + "\n" + "\n".join((verdict or {}).get("lines") or [])
        if not (REPEAT_THE_CHECK.search(said) and "дефектовк" in said.lower()):
            problems.append("не названы оба пути: повторить проверку и дефектовка")
    if row["case"] == "failed":
        opened = [e["name"] for t in (diag, tick) for e in t.of("tool_started") if e.get("name") in MANUAL_TOOLS]
        if opened:
            problems.append(f"сбой записи, а руководство открыто: {', '.join(opened)}")
    pending = tick.one("ticket_pending")
    if bool(pending) != row["ticket_allowed"]:
        want = "заявка до листа подтверждения" if row["ticket_allowed"] else "без заявки"
        problems.append(f"ожидалось: {want}; получили: {'черновик' if pending else 'черновика нет'}")
    if pending:
        p = pending.get("payload") or {}
        if (p.get("vehicle_id"), p.get("session_id")) != (row["vehicle_id"], row["session_id"]):
            problems.append(f"заявка на {p.get('vehicle_id')} / {p.get('session_id')}")
        if not p.get("references"):
            problems.append("в заявке нет ссылок")
        for ref in p.get("references") or []:
            if ref.get("manual") not in designations:
                problems.append(f"ссылка заявки на «{ref.get('manual')}» — не руководство этого двигателя")
            doc = next((d for d in docs.values() if ref.get("manual") in (d.doc_id, d.designation)), None)
            if doc and not 1 <= int(ref.get("pdf_page") or 0) <= doc.pages:
                problems.append(f"ссылка заявки: стр. {ref.get('pdf_page')} вне {doc.doc_id}")
        if p.get("anomaly_type") != row["fault_type"]:
            problems.append(f"код в заявке {p.get('anomaly_type')}, в проверке {row['fault_type']}")
        if not p.get("operations"):
            problems.append("в заявке нет работ")
    if sent:
        problems.append(f"заявок ушло в ТОиР: {sent}")
    return problems, notes


def run_one(row: dict[str, Any], base: str, out: Path) -> dict[str, Any]:
    phone = Phone(base)
    before = tickets(phone, row["vehicle_id"])
    t0 = time.monotonic()
    try:
        diag = ask_once(phone, row["vehicle_id"], DIAG, row["session_id"], new=True)
        tick = ask_once(phone, row["vehicle_id"], TICKET, row["session_id"], new=False)
    except Exception as exc:  # одна сломанная нить не теряет остальные
        return {"row": row, "problems": [f"не дошла до конца: {type(exc).__name__}: {exc}"[:300]], "notes": [],
                "rub": 0.0, "seconds": 0.0, "crashed": True}  # fmt: skip
    sent = tickets(phone, row["vehicle_id"]) - before
    problems, notes = judge(row, diag, tick, phone.sources, sent)
    rub = sum(float(u.get("cost_rub") or 0) for t in (diag, tick) for u in t.of("usage"))
    item = {
        "row": row,
        "problems": problems,
        "notes": notes,
        "rub": round(rub, 4),
        "seconds": round(time.monotonic() - t0, 1),
        "tools": [e.get("name") for t in (diag, tick) for e in t.of("tool_started")],
        "pending": bool(tick.one("ticket_pending")),
        "sent": sent,
    }
    full = {**item, "sources": list(phone.sources.values()), "diagnosis": diag.events, "ticket": tick.events}
    (out / f"{row['session_id']}.json").write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
    return item


def report(label: str, base: str, items: list[dict[str, Any]]) -> str:
    by_why: Counter[str] = Counter()
    clean: Counter[str] = Counter()
    for it in items:
        for why in it["row"]["why"]:
            by_why[why] += 1
            clean[why] += not it["problems"]
    rub = sum(it["rub"] for it in items)
    sent = sum(it.get("sent", 0) for it in items)
    lines = [
        "# Живой агент по ячейкам двигатель × неисправность и особым проверкам",
        "",
        f"Замер `{label}` ({datetime.now():%Y-%m-%d %H:%M}), сервис {base}. Скрипт: `make eval-sweep` "
        "(`scripts/eval_sweep.py`; что считается замечанием — там же). Нити целиком — `.state/eval-sweep/`, вне git.",
        "",
        f"Нитей: {len(items)}, без замечаний: {sum(not it['problems'] for it in items)}. "
        f"Черновиков заявки до листа: {sum(it.get('pending', False) for it in items)}; отправлено в ТОиР: {sent}. "
        f"Всего {rub:.2f} ₽, {rub / max(len(items), 1):.3f} ₽ на нить (два хода).",
        "",
        "| Выбрана как | Нитей | Без замечаний |",
        "|---|---:|---:|",
        *[f"| `{why}` | {n} | {clean[why]} |" for why, n in sorted(by_why.items())],
    ]
    bad = [it for it in items if it["problems"]]
    if bad:
        lines += ["", "## Замечания", "", "| Проверка | Двигатель | Неисправность | Замечание |", "|---|---|---|---|"]
        for it in bad:
            r = it["row"]
            for p in it["problems"]:
                cell = p.replace("|", "/").replace("\n", " ")
                lines.append(f"| {r['session_id']} | {r['engine_model']} | {r['fault_type'] or r['case']} | {cell} |")
    noted = [it for it in items if it["notes"]]
    if noted:
        lines += ["", "## Разные правила двух версий (не замечания)", "", "| Проверка | Двигатель | Неисправность | "
                  "Пометка |", "|---|---|---|---|"]  # fmt: skip
        for it in noted:
            r = it["row"]
            for n in it["notes"]:
                lines.append(f"| {r['session_id']} | {r['engine_model']} | {r['fault_type'] or r['case']} | {n} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default=os.environ.get("EVAL_URL") or URL)
    ap.add_argument("--list", action="store_true", help="напечатать выбранные проверки и выйти")
    ap.add_argument("--only", help="проверки, коды или ячейки через запятую: S-0032,F03,ЯМЗ-536:F03")
    ap.add_argument("--label", default=f"{datetime.now():%Y%m%d-%H%M}")
    ap.add_argument("--concurrency", type=int, default=4, help="стенд: 1 (лимит 10 вопросов в минуту)")
    args = ap.parse_args()
    rows = [json.loads(ln) for ln in EXPECTED.read_text(encoding="utf-8").splitlines() if ln.strip()]
    f = fleet()
    for r in rows:  # ожидания выведены из того же файла парка — проверить, что он не разошёлся
        v = f.vehicle(r["vehicle_id"])
        s = next((s for s in (v.sessions if v else []) if s.session_id == r["session_id"]), None)
        if s is None or s.status != r["status"] or s.anomaly_type != r["fault_type"]:
            raise SystemExit(f"{r['session_id']}: data/vehicles.json разошёлся с {EXPECTED.name}")
    chosen = select(rows)
    if args.only:
        keys = set(args.only.split(","))
        chosen = [r for r in chosen if {r["session_id"], str(r["fault_type"]), f"{r['engine_model']}:{r['fault_type']}"}
                  & keys]  # fmt: skip
    if args.list:
        for r in chosen:
            print(r["session_id"], r["vehicle_id"], r["engine_model"], r["fault_type"] or r["case"], ",".join(r["why"]))
        print(f"{len(chosen)} проверок: {dict(Counter(w for r in chosen for w in r['why']))}")
        return 0
    out = STATE / args.label
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        items = list(pool.map(lambda r: run_one(r, args.url, out), chosen))
    for it in items:
        r = it["row"]
        mark = "ok" if not it["problems"] else "; ".join(it["problems"])
        print(f"{r['session_id']} {r['engine_model']} {r['fault_type'] or r['case']}: {mark} · {it['rub']:.3f} ₽")
    text = report(args.label, args.url, items)
    if not args.only:
        MD.write_text(text, encoding="utf-8")
    print(text.split("\n\n")[2])
    sent = sum(it.get("sent", 0) for it in items)
    return 1 if sent or any(it.get("crashed") for it in items) else 0


if __name__ == "__main__":
    sys.exit(main())
