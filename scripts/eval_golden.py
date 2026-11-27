"""Контрольные вопросы Никиты через настоящий API (`/api/v2/chat`, SSE): проверка кодом, без модели-судьи.

    make eval-golden                                   # оба набора против http://127.0.0.1:8000 (make run)
    make eval-golden EVAL_SET=heldout EVAL_URL=https://<стенд>/ LABEL=stand-1
    uv run python scripts/eval_golden.py --only torque-236,h536-adblue --show

Наборы (`data/eval/`, перенесены из версии Никиты, написаны в спринте 26–27.11):
  - `golden.jsonl` — 36 контрольных вопросов с принятыми страницами и числами, сверенными по PDF;
  - `heldout.jsonl` — 48 вопросов, написанных вслепую по PDF отдельными прогонами модели, которые не видели ни кода,
    ни промптов. В файлах — вопросы, числа и номера страниц; текста руководств нет.

Каждый вопрос — свой «телефон» (своя кука = своя нить), как `make demo-check`. Если у вопроса есть проверка
(`session_id`), сначала «Получить результат диагностики», потом вопрос; нет — последняя проверка машины со статусом
normal (иначе последняя), чтобы карточка неисправности не уводила ответ. Заявку раннер не отправляет никогда.

Проверки (каждая — только там, где применима; вопрос засчитан, если прошли все):
  numbers         все числа хотя бы одной принятой альтернативы есть в ответе («107,9» ≠ «1107,95»);
  page            среди страниц, на которые ответ ссылается [S…], есть принятая (и страницы блока противоречия);
  refuses         где руководство молчит — отказ словами (наши и `clean_refusal.REFUSAL`) или ни числа, ни ссылки;
  says / clean    ответ называет нужное / не содержит запрещённого (регулярные выражения вопроса);
  own_engine      ни одной ссылки на руководство другого двигателя;
  ban_sourced     у фразы с запретом эксплуатации — своя ссылка на страницу;
  opinion_clean   во фразах «мнение помощника, не из руководства» — ни ссылки, ни числа, ни запрета;
  risk_explained  объяснение неисправности говорит, чем она грозит: со ссылкой или с пометкой «мнение помощника»;
  no_diagnosis / both_ways   неисправность, которой у двигателя нет: без разделов разбора, «повторить проверку» и
                  «дефектовка»;
  no_ticket       не было черновика заявки (`ticket_pending`); no_ticket_sent — заявок по машине не прибавилось;
  nothing_withdrawn  проверка кода не убрала ни одной фразы с числом (`verification.counts.unverified`).

Отличия от проверок у Никиты (его формат ответа другой — проверка подогнана под формат, а не под ответы):
  - вопрос не на русском засчитывается без требования «ответ по-русски»: здесь ответ на языке механика (D-45);
  - его «Предположения, не из руководства» здесь — пометка «мнение помощника, не из руководства» во фразе;
  - разделы «Что проверить» / «Чем это грозит» здесь — «Проверки» / «Гипотезы»; «прямого указания нет» здесь
    пишется и как «прямого запрета не нашёл» (`SAYS_EQUIV`);
  - «заглушите двигатель» в шаге повторной записи или работ («заглушить, дать остыть») — не запрет (`NOT_A_BAN`);
  - фразы, запрещённые правилом заказчика 27.11 («обратитесь к специалисту…»), считаются отдельно, на итог не влияют.

Ответы целиком — в `.state/eval-golden/` (вне git: в них пересказ руководств). В отчёт идут номера вопросов,
проверки, страницы, ₽ и секунды: `reports/eval-golden.md` и `reports/eval-golden/<замер>-<набор>.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from demo_check import DIAG, Phone, Turn  # noqa: E402
from service.clean_refusal import REFUSAL as SERVICE_REFUSAL  # noqa: E402
from service.clean_refusal import is_refusal  # noqa: E402
from service.contradictions import HEADER as CONTRA_HEADER  # noqa: E402
from service.fleet import Vehicle, fleet  # noqa: E402
from service.manuals.catalog import documents_for_engine  # noqa: E402

SETS = {"golden": ROOT / "data" / "eval" / "golden.jsonl", "heldout": ROOT / "data" / "eval" / "heldout.jsonl"}
OUT = ROOT / "reports" / "eval-golden"
MD = ROOT / "reports" / "eval-golden.md"
ANSWERS = ROOT / ".state" / "eval-golden"
URL = "http://127.0.0.1:8000"

# ---------- числа (как `app/verify.py` у Никиты: normalise, number_pattern) ----------

_DASHES = re.compile(r"[‐‑‒–—―−]")
HANDLES = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]", re.I)
DESIGNATIONS = re.compile(
    r"(?<![\w])(?:ЯМЗ|ЗМЗ|УМЗ|КамАЗ|КАМАЗ|МАЗ|УАЗ|ПАЗ|ГАЗ|Урал)\s*[-‑–]?\s*\d[\w.\-‑]*"
    r"|\b\d{2,}\.\d{4,}(?:[-‑]\d+)*|(?<![\w])(?:ГОСТ|ОСТ|ТУ)\s*[\d.\-‑]+"
)
NUM_UNIT = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:мм|см|н\s*·?\s*м|нм|кгс|кпа|мпа|бар|атм|°|мл|об/мин|мин-1|%|ом|кг|км|л\b|в\b|а\b|ч\b|с\b)"
)


def normalise(text: str) -> str:
    """Одно написание: NFKC, тире → «-», «120±2о» → «120±2°», пробелы, регистр."""
    text = unicodedata.normalize("NFKC", text.replace("º", "°"))
    text = _DASHES.sub("-", text)
    text = re.sub(r"(?<=\d)\s*[оo](?![а-яёa-z])", "°", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def number_pattern(number: str) -> re.Pattern[str]:
    """«107,9» находится как «107,9», «107.9» или «107, 9» — и не внутри «1107,95»."""
    body = r"\s*[.,]\s*".join(re.escape(g) for g in re.split(r"[.,]", number))
    return re.compile(rf"(?<![\d])(?<!\d[.,]){body}(?![\d])(?![.,]\d)")


def has_number(text: str, number: str) -> bool:
    return bool(number_pattern(number).search(normalise(text)))


def has_values(text: str) -> bool:
    """Есть число с единицей (без обозначений вида «ЯМЗ-236» и ссылок [S…])."""
    return bool(NUM_UNIT.search(normalise(DESIGNATIONS.sub(" ", HANDLES.sub(" ", text)))))


# ---------- отказ, запрет, мнение ----------

REFUSAL = re.compile(
    r"данных недостаточно|данных нет|этого нет|нет в руководстве|такого узла нет|не приведен|не приводится"
    r"|в руководств\w+ [^\n]{0,140}?\bнет\b|прямого указания [^\n]{0,80}?нет|не описан|не могу ответить"
    r"|ответить .{0,40}?не могу|только по руководств|не относится|не про этот двигатель"
    r"|ответить не получится|привести нельзя|руководств\w* на [^\n]{0,40}?нет|данных по [^\n]{0,40}?нет"
    r"|данных [^\n]{0,80}?недостаточно|назвать нельзя|не (?:привожу|приведу|назову|подскажу)"
    r"|ничего не скажу|не подключено|(?:дать|назвать) не могу|для этого двигателя нет|на н[её]м нет"
    r"|здесь не найти|руководств\w* (?:по|на) [^\n]{0,60}?недоступн"
    r"|сказать нечего|на этом двигателе [^\n]{0,60}?\bнет\b|для него не существует"
    # формулировки ответа кода здесь (`absent_parts`, `other_engine`): «У ЗМЗ-5234.10 нет турбокомпрессора»
    r"|\bу (?:ЗМЗ|ЯМЗ)[-\w.]* нет\b|не применим",
    re.I,
)
BAN = re.compile(
    r"нельзя (?:выпускать|эксплуатировать|ехать|продолжать (?:работу|движение|эксплуатаци|поездк))"
    r"|(?:выпускать|ехать|эксплуатировать|продолжать движение)(?: [а-яё]+){0,3} нельзя"
    r"|эксплуатаци\w+(?: [а-яё]+){0,2} (?:запрещ\w+|не допуска\w+|недопустим\w+)"
    r"|не допуска\w+ (?:эксплуатаци|работ\w+ двигател)|работа двигателя не допуска\w+|не эксплуатировать"
    r"|эксплуатировать запрещ\w+|запрещ\w+ (?:эксплуатаци|выпуск|выезд)|выезд\w* запрещ\w+"
    r"|выпуск\w*(?: в рейс| на линию)? (?:запрещ\w+|нельзя)|на линию не выпускать|в рейс не выпускать"
    r"|(?:остановить|заглушить|остановите|заглушите) двигатель|двигатель (?:нужно|надо|следует) остановить"
    r"|двигатель не заводить",
    re.I,
)
NO_BAN = re.compile(
    r"(?:прям\w+ (?:указани\w+|запрет\w+)|указани\w+|запрет\w+|требовани\w+)[^.\n]{0,120}?"
    r"(?:\bнет\b|не найден\w*)|не сказано|не запрещ|не говорит|не пишет|не требует",
    re.I,
)
_CLAUSE = re.compile(r",\s*(?:но|однако|поэтому|а)\s+|;\s*")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z«(\d])")
_LIST = re.compile(r"^\s*(?:\d+[.)]|[-–—•*])\s+")
OPINION = "мнение помощника"  # agent.OPINION_MARK: «(мнение помощника, не из руководства)»
RISK = re.compile(
    r"\bгроз|\bопасн|\bриск|может привести|привед[её]т к|приводит к|последстви|\bавари|разрушени|поломк|заклинив"
    r"|выход\w* из строя",
    re.I,
)
DIAG_HEADINGS = re.compile(r"^\W*(?:наблюдения|гипотезы|возможный ремонт)\W*$", re.I | re.M)
REPEAT_THE_CHECK = re.compile(r"повтор\w*\s+(?:акустическ\w+\s+)?(?:проверк|запис)", re.I)
# Правило заказчика 27.11: механик сам специалист — «обратитесь к …» вместо шага не годится
BANNED = re.compile(
    r"обратитесь к (?:специалист|мастер|главн\w+ механик|изготовител|дилер)\w*|уточн\w+ у (?:специалист|дилер)\w*",
    re.I,
)
# Слова ответа у Никиты → те же по смыслу здесь (разделы и формулировка «прямого указания нет»)
SAYS_EQUIV = {"что проверить": ("что проверить", "проверки", "проверить"),
              "предположения, не из руководства": ("предположения, не из руководства", OPINION),
              "прямого указания": ("прямого указания", "прямого запрета")}  # fmt: skip
# Шаг повторной акустической записи («заглушите двигатель, закрепите датчик») — не запрет эксплуатации
NOT_A_BAN = re.compile(r"повтор\w*\s+(?:акустическ\w+\s+)?(?:проверк|запис)|датчик|остыть|остынет", re.I)
_SERVICE_LINE = re.compile(r"^\s*\**(?:Понадобится|Безопасность|Инструмент)\w*\**\s*:", re.I | re.M)


def refusal_kind(answer: str, cited: set[tuple[str, int]]) -> str | None:
    """Отказ словами (наш список или `clean_refusal`) — «wording»; ни числа с единицей, ни ссылки — «no number»."""
    if REFUSAL.search(answer) or SERVICE_REFUSAL.search(answer):
        return "wording"
    if not has_values(answer) and not cited:
        return "no number"
    return None


def sentences(answer: str) -> list[tuple[str, str, str]]:
    """(фраза, её строка, строка-заголовок списка над ней) — для правил «запрет со ссылкой» и «мнение»."""
    out, intro = [], ""
    for line in answer.split("\n"):
        if not line.strip():
            continue
        is_item = bool(_LIST.match(line))
        for part in _SENTENCE.split(line):
            if part.strip():
                out.append((part, line, intro if is_item else ""))
        if not is_item:
            intro = line if line.rstrip().endswith(":") else ""
    return out


def discipline(answer: str) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    bans = [
        (s, line, intro)
        for s, line, intro in sentences(answer)
        if any(BAN.search(c) and not NO_BAN.search(c) for c in _CLAUSE.split(s)) and not NOT_A_BAN.search(s)
    ]
    if bans:
        checks["ban_sourced"] = all(
            HANDLES.search(s) or (not HANDLES.search(line) and HANDLES.search(intro)) for s, line, intro in bans
        )
    opinions = [s for s, _, _ in sentences(answer) if OPINION in s.lower()]
    if opinions:
        checks["opinion_clean"] = not any(HANDLES.search(s) or has_values(s) or BAN.search(s) for s in opinions)
    return checks


def says(answer: str, wanted: list[str]) -> bool:
    low = answer.lower()
    return any(alt in low for w in wanted for alt in SAYS_EQUIV.get(w.lower(), (w.lower(),)))


# ---------- прогон ----------


def session_for(q: dict[str, Any], v: Vehicle) -> str:
    if q.get("session_id"):
        return str(q["session_id"])
    normal = [s for s in v.sessions if s.status == "normal"]
    return (normal or v.sessions)[-1].session_id


def shown(turn: Turn) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    """Что видит механик: текст ответа и блок противоречия (его код вырезает из текста в отдельную карточку)."""
    blocks = [e.get("block") or {} for e in turn.of("tool_result")]
    contra = next((b for b in blocks if b.get("kind") == "contradiction"), None)
    verdict = next((b for b in blocks if b.get("kind") == "verdict"), None)
    text = turn.text
    if contra:
        items = "\n".join(f"- «{i['quote']}» [{i['handle']}]" if i.get("handle") else f"- «{i['quote']}»"
                          for i in contra.get("items") or [])  # fmt: skip
        text += f"\n\n{CONTRA_HEADER} — {contra.get('title', '')}:\n{items}\n{contra.get('conclusion', '')}"
    return text, [i for i in (contra or {}).get("items") or [] if i.get("manual_id")], verdict


def grade(q: dict[str, Any], r: dict[str, Any], own: set[str]) -> dict[str, bool]:
    answer: str = r["answer"]
    shown_all = answer + ("\n" + r["verdict_text"] if r.get("verdict_text") else "")
    cited = {(m, p) for m, p in r["cited"]}
    checks: dict[str, bool] = {}
    accepted = {(m, p) for alt in q["accept"] for m, p in alt["pages"]}
    numeric = [alt for alt in q["accept"] if alt["numbers"]]
    if numeric:
        hit = [all(has_number(answer, n) for n in alt["numbers"]) for alt in numeric]
        checks["numbers"] = all(hit) if q["all_alternatives"] else any(hit)
    if accepted and not q["must_refuse"]:
        checks["page"] = bool(cited & accepted)
    if q["any_of"]:
        checks["says"] = says(shown_all, q["any_of"])
    if q["must_refuse"]:
        checks["refuses"] = refusal_kind(answer, cited) is not None
    if q["must_not_match"]:
        checks["clean"] = not any(re.search(p, shown_all, re.I | re.S) for p in q["must_not_match"])
    if q.get("no_ticket"):
        checks["no_ticket"] = "ticket_pending" not in r["events"]
    if q.get("no_ticket_sent"):
        checks["no_ticket_sent"] = r["tickets_sent"] == 0
    checks["own_engine"] = all(m in own for m, _ in cited)
    checks |= discipline(answer)
    if q["kind"] in ("explain", "risk"):
        checks["risk_explained"] = any(
            RISK.search(s) and (HANDLES.search(s) or OPINION in s.lower()) for s, _, _ in sentences(answer)
        )
    if q["kind"] == "mismatch":
        checks["no_diagnosis"] = not DIAG_HEADINGS.search(answer)
        checks["both_ways"] = bool(REPEAT_THE_CHECK.search(shown_all)) and "дефектовк" in shown_all.lower()
    if not q.get("withdrawal_expected"):
        checks["nothing_withdrawn"] = r["withdrawn"] == 0
    return checks


def failure_class(q: dict[str, Any], r: dict[str, Any]) -> str | None:
    """Первая причина провала по порядку важности (разбор человеком — в отчёте PR)."""
    c = r["checks"]
    if r.get("error"):
        return "сбой"
    if c.get("own_engine") is False:
        return "чужой двигатель"
    if c.get("refuses") is False:
        return "ответ, где руководство молчит"
    body = "\n".join(ln for ln in r["answer"].split("\n") if not _SERVICE_LINE.match(ln))
    declined = is_refusal(r["answer"]) or bool(REFUSAL.search(body) or SERVICE_REFUSAL.search(body))
    if (c.get("page") is False or c.get("numbers") is False) and c.get("numbers") is not True and declined:
        return "отказ, где ответ есть"
    if c.get("numbers") is False:
        return "неверное или нет числа"
    if c.get("page") is False:
        return "неверная или нет страницы"
    named = {"ban_sourced": "запрет без страницы", "both_ways": "не названы оба пути", "says": "не названо нужное",
             "clean": "есть запрещённое", "nothing_withdrawn": "проверка кода сняла фразу с числом",
             "opinion_clean": "мнение со ссылкой или числом", "risk_explained": "не сказано, чем грозит"}  # fmt: skip
    failed = [named.get(k, k) for k, ok in c.items() if not ok]
    return failed[0] if failed else None


def tickets(phone: Phone, vehicle_id: str) -> int:
    resp = phone.http.get(f"{phone.base}/api/v2/vehicles/{vehicle_id}/tickets")
    return len(resp.json()) if resp.status_code == 200 else 0


def ask_once(phone: Phone, vehicle: str, message: str, session: str, new: bool) -> Turn:
    """429 (лимит частоты стенда) — подождать и повторить; иное — исключение."""
    for attempt in range(6):
        try:
            return phone.ask(vehicle, message, session, new=new)
        except Exception as exc:
            if "429" not in str(exc) or attempt == 5:
                raise
            time.sleep(15 * (attempt + 1))
    raise RuntimeError("unreachable")


def run_one(q: dict[str, Any], base: str) -> dict[str, Any]:
    v = fleet().vehicle(q["vehicle_id"])
    if v is None:
        raise SystemExit(f"{q['id']}: машины {q['vehicle_id']} нет в data/vehicles.json")
    session = session_for(q, v)
    phone = Phone(base)
    before = tickets(phone, v.vehicle_id)
    messages = ([DIAG] if q.get("session_id") and q["question"] != DIAG else []) + [q["question"]]
    t0 = time.monotonic()
    rub, turn = 0.0, None
    try:
        for n, message in enumerate(messages):
            turn = ask_once(phone, v.vehicle_id, message, session, new=n == 0)
            rub += sum(float(u.get("cost_rub") or 0) for u in turn.of("usage"))
        if turn is None:
            raise RuntimeError("нет ни одного хода")
        answer, contra_items, verdict = shown(turn)
        error = turn.error
    except Exception as exc:  # сбой одного вопроса — провал вопроса, не прогона
        answer, contra_items, verdict, error = "", [], None, f"{type(exc).__name__}: {exc}"[:300]
    cited = set()
    for h in HANDLES.findall(answer):
        for one in re.split(r"[,;]", h):
            s = phone.sources.get(one.strip().upper())
            if s and s.get("manual_id"):
                cited.add((s["manual_id"], int(s["pdf_page"])))
    cited |= {(i["manual_id"], int(i["pdf_page"])) for i in contra_items}
    ver = (turn.one("verification") if turn else None) or {}
    r: dict[str, Any] = {
        "id": q["id"],
        "kind": q["kind"],
        "session": session,
        "answer": answer,
        "verdict_text": "\n".join([verdict.get("headline") or "", *(verdict.get("lines") or [])]) if verdict else "",
        "cited": sorted(cited),
        "events": sorted({e.get("type", "") for e in (turn.events if turn else [])}),
        "withdrawn": int((ver.get("counts") or {}).get("unverified") or 0),
        "tickets_sent": tickets(phone, v.vehicle_id) - before,
        "rub": round(rub, 4),
        "seconds": round(turn.seconds if turn else 0.0, 1),
        "total_seconds": round(time.monotonic() - t0, 1),
        "tools": [e.get("name") for e in (turn.of("tool_started") if turn else [])],
        "error": error,
    }
    return judge(q, r)


def judge(q: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    """Проверки по сохранённому ответу — и после прогона, и при `--regrade` (без модели)."""
    v = fleet().vehicle(q["vehicle_id"])
    own = {d.doc_id for d in documents_for_engine(v.engine_model)} if v else set()
    answer = r["answer"]
    r["checks"] = {"ran": False} if r.get("error") else grade(q, r, own)
    r["passed"] = all(r["checks"].values())
    r["banned"] = [m.group(0) for m in BANNED.finditer(answer)]
    r["refusal"] = refusal_kind(answer, {(m, p) for m, p in r["cited"]}) if q["must_refuse"] else None
    r["class"] = failure_class(q, r) if not r["passed"] else None
    return r


def summarise(name: str, label: str, base: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    def share(key: str) -> dict[str, int]:
        rel = [r for r in results if key in r["checks"]]
        return {"ok": sum(1 for r in rel if r["checks"][key]), "of": len(rel)}

    secs = sorted(r["seconds"] for r in results if not r.get("error")) or [0.0]
    classes: dict[str, int] = {}
    for r in results:
        if r["class"]:
            key = r["class"].split(":")[0]
            classes[key] = classes.get(key, 0) + 1
    return {
        "label": label,
        "set": name,
        "url": base,
        "at": f"{datetime.now():%Y-%m-%d %H:%M}",
        "questions": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "page": share("page"),
        "numbers": share("numbers"),
        "refuses": share("refuses"),
        "refusals_by_wording": sum(1 for r in results if r["refusal"] == "wording" and r["checks"].get("refuses")),
        "says": share("says"),
        "clean": share("clean"),
        "foreign": sum(1 for r in results if r["checks"].get("own_engine") is False),
        "ban_sourced": share("ban_sourced"),
        "opinion_clean": share("opinion_clean"),
        "withdrawn_answers": sum(1 for r in results if r["withdrawn"]),
        "banned_answers": sum(1 for r in results if r["banned"]),
        "tickets_sent": sum(r["tickets_sent"] for r in results),
        "errors": sum(1 for r in results if r.get("error")),
        "classes": classes,
        "rub_total": round(sum(r["rub"] for r in results), 2),
        "rub_per_question": round(sum(r["rub"] for r in results) / max(len(results), 1), 3),
        "seconds_p50": round(statistics.median(secs), 1),
        "seconds_p95": secs[min(len(secs) - 1, round(0.95 * (len(secs) - 1)))],
        "results": [{k: v for k, v in r.items() if k not in ("answer", "verdict_text", "question")} for r in results],
    }


def part(d: dict[str, int]) -> str:
    return f"{d['ok']}/{d['of']}" if d["of"] else "—"


def write_md() -> str:
    runs = sorted(
        (json.loads(p.read_text(encoding="utf-8")) for p in OUT.glob("*.json")),
        key=lambda d: (d["at"], d["set"] != "golden"),
    )
    lines = [
        "# Контрольные вопросы через `/api/v2/chat`",
        "",
        "Наборы — `data/eval/golden.jsonl` (36, страницы и числа сверены по PDF) и `data/eval/heldout.jsonl` (48,",
        "написаны вслепую по PDF отдельными прогонами модели, не видевшими кода и промптов). Скрипт:",
        "`make eval-golden` (`scripts/eval_golden.py`, там же — что значит каждая проверка). Ответы целиком — в",
        "`.state/eval-golden/`, вне git.",
        "",
        "| Замер | Набор | Где | Засчитано | Страница | Числа | Отказы | Чужой двигатель | Фраза снята | ₽ на вопрос | с, медиана / p95 |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        lines.append(
            f"| `{r['label']}` ({r['at']}) | {r['set']} | {r['url']} | {r['passed']}/{r['questions']} | "
            f"{part(r['page'])} | {part(r['numbers'])} | {part(r['refuses'])} | {r['foreign']} | "
            f"{r['withdrawn_answers']} | {r['rub_per_question']} | {r['seconds_p50']} / {r['seconds_p95']} |"
        )
    latest: dict[str, dict[str, Any]] = {}
    for r in runs:
        latest[r["set"]] = r
    for name, r in latest.items():
        lines += [
            "",
            f"## {name}: `{r['label']}` ({r['at']})",
            "",
            f"Засчитано {r['passed']}/{r['questions']}. Запрет со ссылкой {part(r['ban_sourced'])}, мнение без "
            f"ссылок и чисел {part(r['opinion_clean'])}, называет нужное {part(r['says'])}, без запрещённого "
            f"{part(r['clean'])}; отказов словами {r['refusals_by_wording']}; ответов с «обратитесь к…» "
            f"{r['banned_answers']}; заявок отправлено {r['tickets_sent']}; сбоев {r['errors']}; "
            f"всего {r['rub_total']} ₽.",
            "",
            "Провалы по классам: " + (", ".join(f"{k} — {n}" for k, n in r["classes"].items()) or "нет") + ".",
            "",
            "| № | Вид | Итог | Не прошло | Класс | Страницы ответа | ₽ | с |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for x in r["results"]:
            failed = ", ".join(k for k, ok in x["checks"].items() if not ok) or "—"
            pages = ", ".join(f"{m} {p}" for m, p in x["cited"]) or "—"
            lines.append(f"| {x['id']} | {x['kind']} | {'✅' if x['passed'] else '❌'} | {failed} | "
                         f"{x['class'] or '—'} | {pages} | {x['rub']} | {x['seconds']} |")  # fmt: skip
    MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return MD.name


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default=os.environ.get("EVAL_URL") or URL, help="сервис: make run или стенд")
    ap.add_argument("--set", default="all", choices=["all", *SETS])
    ap.add_argument("--only", help="номера через запятую")
    ap.add_argument("--label", default=f"{datetime.now():%Y%m%d-%H%M}")
    ap.add_argument("--concurrency", type=int, default=4, help="стенд: 1–2 (лимит 10 вопросов в минуту)")
    ap.add_argument("--show", action="store_true", help="печатать ответы (в отчёт не идут)")
    ap.add_argument("--regrade", action="store_true",
                    help="заново оценить ответы замера --label из .state/eval-golden (без модели); вопросы со сбоем "
                         "связи — задать заново")  # fmt: skip
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None
    code = 0
    for name, path in SETS.items():
        if args.set not in ("all", name):
            continue
        qs = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        qs = [q for q in qs if not only or q["id"] in only]
        if not qs:
            continue
        by_id = {q["id"]: q for q in qs}
        if args.regrade:
            saved_file = ANSWERS / f"{args.label}-{name}.jsonl"
            saved = [json.loads(ln) for ln in saved_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
            results = [run_one(by_id[r["id"]], args.url) if r.get("error") else judge(by_id[r["id"]], r)
                       for r in saved if r["id"] in by_id]  # fmt: skip
        else:
            with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
                results = list(pool.map(lambda q: run_one(q, args.url), qs))
        ANSWERS.mkdir(parents=True, exist_ok=True)
        with (ANSWERS / f"{args.label}-{name}.jsonl").open("w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps({**r, "question": by_id[r["id"]]["question"]}, ensure_ascii=False) + "\n")
        for r in results:
            mark = "✅" if r["passed"] else "❌"
            bad = ", ".join(k for k, ok in r["checks"].items() if not ok)
            print(f"{r['id']} {mark} {r['rub']:.3f} ₽ {r['seconds']} с {bad} {r['class'] or ''} {r['cited']}")
            if args.show:
                print("   " + r["answer"].replace("\n", "\n   ")[:2000])
        s = summarise(name, args.label, args.url, results)
        if not only:
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{args.label}-{name}.json").write_text(json.dumps(s, ensure_ascii=False, indent=1) + "\n",
                                                           encoding="utf-8")  # fmt: skip
        print(f"{name}: {s['passed']}/{s['questions']} · страница {part(s['page'])} · числа {part(s['numbers'])} · "
              f"отказы {part(s['refuses'])} · чужих {s['foreign']} · снято {s['withdrawn_answers']} · "
              f"{s['rub_per_question']} ₽/вопрос · {s['rub_total']} ₽ · классы {s['classes']}")  # fmt: skip
        code = code or (1 if s["errors"] or s["tickets_sent"] else 0)
    if not only:
        print(f"отчёт: reports/{write_md()}")
    return code


if __name__ == "__main__":
    sys.exit(main())
