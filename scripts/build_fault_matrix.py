"""Сборка матрицы «код × двигатель» (issue #10) из `data/fault_matrix.src.json` и индекса руководств.

Ручное в источнике — решение о применимости и его основание; для ячеек, подписанных инженером в реестре покрытия
(`pages` в источнике), — ещё страницы и работы (`pinned_group`). Остальное собирается из индекса:
  страницы — поиск по запросам кода в руководствах ЭТОГО двигателя, фрагмент обязан называть узел (`must`);
  работы — фразы-указания («Заменить…», «Отрегулировать…») с этих страниц;
  запчасти — что именно «заменить» в этих работах;
  безопасность — «Внимание», «Запрещается»… с этих страниц.
Всё — дословные цитаты. Затем каждая ячейка проверяется (`verify_cell`): документ этого двигателя, страница
существует, цитата на странице. Не прошло — выбрасывается; не прошло основание — ячейка `unknown`.

  uv run --env-file .env python scripts/build_fault_matrix.py      → fault_matrix.json (data/ и INDEX_DIR) + отчёт
Нужен собранный индекс (`make index`). Код возврата 1 — ячейка без статуса или основание не прошло проверку.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from matrix_enrich import REPORT as PARTS_REPORT
from matrix_enrich import enrich, load_pages
from matrix_enrich import report as parts_report
from service.fault_matrix import QUOTE_MAX_WORDS, Cell, Ref, save_matrix, verify_cell
from service.manuals.catalog import ENGINES
from service.manuals.index import Fragment, index_dir, load_fragments
from service.manuals.search import ManualIndex

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "fault_matrix.src.json"
MAX_PAGES, MAX_OPS, MAX_PARTS, MAX_SAFETY = 4, 6, 5, 2

_WS = re.compile(r"\s+")
_SENT = re.compile(
    r"(?<=[.;!?])\s+|\s+(?=\d+\.\d+(?:\.\d+)*\s+[А-ЯЁ])"
    r"|\s*(?:Способ устранения|Метод устранения|Причина|Неисправность):\s*"
)
_OP = re.compile(
    r"^(Заменить|Отрегулировать|Проверить|Подтянуть|Промыть|Очистить|Снять|Установить|Натянуть|Устранить|"
    r"Притереть|Прочистить|Продуть|Слить|Залить|Долить|Затянуть|Отремонтировать|Произвести|Выполнить|"
    r"Прокачать|Удалить|Восстановить|Зачистить|Разобрать|Подрегулировать|Отвернуть|Завернуть|Совместить|"
    r"Провернуть|Подтянуть|Отрегулируйте|Замените|Проверьте|Смазать|Нанести|Переставить|Довернуть)\b",
    re.I,
)
_REPLACE = re.compile(
    r"\b[Зз]аменить\s+(?:неисправн[а-я]+\s+)?([а-яё][а-яё\s-]{3,60}?)(?=[,.;(]|\s+(?:и|или|при|в|на|с)\s|$)"
)
_SAFETY = re.compile(r"Внимание|ВНИМАНИЕ|[Зз]апрещается|Не допуска|ОПАСНОСТЬ|ПРЕДУПРЕЖДЕНИЕ|Осторожно")


def flat(text: str) -> str:
    return _WS.sub(" ", text.replace("|", " ")).strip()


_ENUM = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[а-я]\)|[-–•])\s+")


def sentences(text: str) -> list[str]:
    """Предложения фрагмента без номера пункта в начале («6.4.1 Проверить…» → «Проверить…»)."""
    out = []
    for s in _SENT.split(flat(text)):
        s = s.strip(" -–") if s else ""
        while s and _ENUM.match(s):
            s = _ENUM.sub("", s, count=1)
        if s.count("(") > s.count(")"):  # «;» внутри скобок разрезал фразу — хвост со скобкой отбрасываем
            s = s[: s.rfind("(")].rstrip(" ,")
        if len(s) > 3:
            out.append(s)
    return out


def what_of(text: str) -> str:
    t = text.lower()
    if re.search(r"неисправност|причина|способ устранения|метод устранения", t):
        return "неисправности"
    if "регулир" in t:
        return "регулировка"
    if re.search(r"снят|установ|разборк|сборк|ремонт|замен|дефект", t):
        return "ремонт"
    if "провер" in t:
        return "проверка"
    if re.search(r"\d+[,.]?\d*\s*(мм|кпа|мпа|н·м|нм|кгс)", t):
        return "нормы"
    return "устройство"


_CHUNK = re.compile(r"[^\s|]+")
_WORD = re.compile(r"\w+")
_LEAD_WORDS = 8  # столько слов до упоминания узла цитата может взять, чтобы начаться с ячейки или предложения


def window(text: str, must: re.Pattern[str], limit: int = QUOTE_MAX_WORDS) -> str:
    """Короткая дословная цитата вокруг первого упоминания узла: не длиннее `limit` слов (`\\w+`), начало и
    конец — на границе слов. Начинается с ближайшего к узлу начала ячейки таблицы, строки или предложения не дальше
    `_LEAD_WORDS` слов до узла, иначе — с самого слова узла; кончается концом предложения, если оно влезает.
    Цитата — подстрока `flat(text)`: куски между пробелами и «|» через один пробел."""
    chunks: list[tuple[str, int, bool]] = []  # (кусок, его начало в flat, начало ячейки / строки / предложения)
    pos, prev_end = 0, 0
    for m in _CHUNK.finditer(text):
        gap = text[prev_end : m.start()]
        # начало ячейки или предложения: после «|», после «.;:!?» или с заглавной в начале строки (перенос внутри
        # фразы — со строчной, с него не начинаем)
        strong = not chunks or "|" in gap or chunks[-1][0][-1] in ".;:!?" or ("\n" in gap and m.group()[0].isupper())
        chunks.append((m.group(), pos, strong))
        pos += len(m.group()) + 1
        prev_end = m.end()
    if not chunks:
        return ""
    hit = must.search(" ".join(c for c, _, _ in chunks))
    j = 0 if hit is None else max(i for i, (_, at, _) in enumerate(chunks) if at <= hit.start())
    lo, words = j, 0
    while lo > 0 and words + len(_WORD.findall(chunks[lo - 1][0])) <= _LEAD_WORDS:
        lo -= 1
        words += len(_WORD.findall(chunks[lo][0]))
    start = next((k for k in range(j, lo - 1, -1) if chunks[k][2]), j)  # ближайшее к узлу начало ячейки
    while start < j and not _WORD.search(chunks[start][0]):  # не с «-» или «*»
        start += 1
    out: list[str] = []
    words = 0
    for k in range(start, len(chunks)):
        n = len(_WORD.findall(chunks[k][0]))
        if out and words + n > limit:
            break
        out.append(chunks[k][0])
        words += n
        if k >= j and chunks[k][0][-1] in ".!?" and words >= 6:
            break  # предложение с узлом закончилось
    return " ".join(out).rstrip(" ,;:-–—")


def draft_group(
    index: ManualIndex, by_page: dict[tuple[str, int], list[Fragment]], engine: str, spec: dict[str, Any]
) -> tuple[list[Ref], list[Ref], list[Ref], list[Ref]]:
    must = re.compile(spec["must"], re.I)
    ranked: list[list[tuple[str, int]]] = []
    for q in spec["queries"]:
        hits = index.search(q, engine, k=10)
        ranked.append([(h.fragment.doc_id, h.fragment.page) for h in hits if must.search(h.fragment.text)])
    order: list[tuple[str, int]] = []
    for rank in range(10):  # по очереди лучшие из каждого запроса
        for r in ranked:
            if rank < len(r) and r[rank] not in order:
                order.append(r[rank])
    pages: list[Ref] = []
    ops: list[Ref] = []
    parts: list[Ref] = []
    safety: list[Ref] = []
    for key in order[:MAX_PAGES]:
        frags = by_page[key]
        hit = next(f for f in frags if must.search(f.text))
        pages.append(Ref(doc=key[0], page=key[1], quote=window(hit.text, must), what=what_of(hit.text)))
        for f in frags:
            # Строка таблицы неисправностей про этот узел: её «способ устранения» узел может не называть
            fault_row = f.source == "таблица" and f.text.startswith(("Неисправность:", "Причина:"))
            row_about_node = fault_row and bool(must.search(f.text))
            for s in sentences(f.text):
                if (
                    _OP.match(s)
                    and len(s) <= 220
                    and (must.search(s) or row_about_node)
                    and all(s != o.quote for o in ops)
                ):
                    ops.append(Ref(doc=key[0], page=key[1], quote=s))
                if _SAFETY.search(s) and 30 <= len(s) <= 260 and must.search(s) and all(s != x.quote for x in safety):
                    safety.append(Ref(doc=key[0], page=key[1], quote=s))
    ops = ops[:MAX_OPS]
    for o in ops:
        for m in _REPLACE.finditer(o.quote):
            part = m.group(1).strip()
            if len(part) >= 5 and all(part != p.quote for p in parts):
                parts.append(Ref(doc=o.doc, page=o.page, quote=part))
    return pages, ops, parts[:MAX_PARTS], safety[:MAX_SAFETY]


_NOT_PINNED_PART = re.compile(r"исправн|комплект", re.I)  # «заменить исправным», «заменить комплектом»


def pinned_group(
    by_page: dict[tuple[str, int], list[Fragment]],
    spec: dict[str, Any],
    decision: dict[str, Any],
    drafted_safety: list[Ref],
) -> tuple[list[Ref], list[Ref], list[Ref], list[Ref]]:
    """Ячейка из реестра покрытия, подписанного инженером (`pages` в источнике): страницы и работы — оттуда, а не из
    поиска. Цитата страницы — из индекса, как у найденных страниц; работы — дословные строки таблиц неисправностей
    и процедур, проверяет `verify_cell`. Запчасти — что «заменить» в этих работах."""
    must = re.compile(spec["must"], re.I)
    pages: list[Ref] = []
    for p in decision["pages"]:
        frags = by_page.get((p["doc"], int(p["page"])))
        if not frags:
            continue  # страницы нет в индексе — проверка ячейки не найдёт и работ с неё
        hit = next((f for f in frags if must.search(f.text)), frags[0])
        pages.append(Ref(doc=p["doc"], page=int(p["page"]), quote=window(hit.text, must), what=p.get("what", "")))
    ops = [Ref.from_json(o) for o in decision.get("operations") or []]
    keys = {(p.doc, p.page) for p in pages}
    safety = [Ref.from_json(x) for x in decision.get("safety") or []]
    safety += [x for x in drafted_safety if (x.doc, x.page) in keys and all(x.quote != y.quote for y in safety)]
    parts: list[Ref] = []
    for o in ops:
        for m in _REPLACE.finditer(o.quote):
            part = m.group(1).strip()
            if len(part) >= 5 and not _NOT_PINNED_PART.search(part) and all(part != x.quote for x in parts):
                parts.append(Ref(doc=o.doc, page=o.page, quote=part))
    return pages, ops, parts[:MAX_PARTS], safety[:MAX_SAFETY]


def build(index_path: Path) -> tuple[list[Cell], list[str]]:
    src = json.loads(SRC.read_text(encoding="utf-8"))
    frags = load_fragments(index_path / "fragments.jsonl")
    by_page: dict[tuple[str, int], list[Fragment]] = defaultdict(list)
    for f in frags:
        by_page[(f.doc_id, f.page)].append(f)
    page_texts = {k: "\n".join(f.text for f in v) for k, v in by_page.items()}

    def page_text(doc: str, page: int) -> str | None:
        return page_texts.get((doc, page))

    index = ManualIndex.load(index_path)
    cells: list[Cell] = []
    problems: list[str] = []
    for code, spec in sorted(src["codes"].items()):
        for group, engines in src["groups"].items():
            decision = spec["cells"][group]
            applicable = decision["applicable"]
            pages: list[Ref] = []
            ops: list[Ref] = []
            parts: list[Ref] = []
            safety: list[Ref] = []
            if applicable != "false":
                pages, ops, parts, safety = draft_group(index, by_page, engines[0], spec)
            if applicable == "true" and decision.get("pages"):  # подписано инженером: страницы и работы из реестра
                pages, ops, parts, safety = pinned_group(by_page, spec, decision, safety)
            basis = Ref.from_json(decision["basis"]) if decision.get("basis") else None
            if applicable == "true" and basis is None and pages:
                basis = Ref(doc=pages[0].doc, page=pages[0].page, quote=pages[0].quote)
            if applicable == "unknown":
                ops, parts = [], []  # работы из неподтверждённой ячейки агенту не нужны
            for engine in engines:
                draft = Cell(
                    code=code,
                    engine=engine,
                    applicable=applicable,
                    basis=basis,
                    why=decision.get("why", ""),
                    inference=bool(decision.get("inference")),
                    note=decision.get("note", ""),
                    pages=list(pages),
                    operations=list(ops),
                    spare_parts=list(parts),
                    safety=list(safety),
                )
                cell, errs = verify_cell(draft, page_text)
                problems += [f"{code} × {engine}: {e}" for e in errs]
                cells.append(cell)
    missing = {(c, e) for c in src["codes"] for e in ENGINES} - {(c.code, c.engine) for c in cells}
    problems += [f"{c} × {e}: ячейки нет" for c, e in sorted(missing)]
    return cells, problems


ICON = {"confirmed": "✅", "not_applicable": "⛔", "silent": "📭", "unknown": "❔"}


def impossible_checks(cells: list[Cell]) -> list[str]:
    by = {(c.code, c.engine): c for c in cells}
    data = json.loads((ROOT / "data" / "vehicles.json").read_text(encoding="utf-8"))
    out = []
    for v in data["vehicles"]:
        for s in v["sessions"]:
            if s["status"] == "anomaly" and s["anomaly_type"]:
                c = by.get((s["anomaly_type"], v["engine_model"]))
                if c and c.applicable == "false":
                    out.append(
                        f"| {v['vehicle_id']} | {s['session_id']} | {s['anomaly_type']} | {v['engine_model']} "
                        f"| {c.why} "
                        f"({c.basis.doc if c.basis else ''}, стр. {c.basis.page if c.basis else ''}) |"
                    )
    return out


def report(cells: list[Cell], problems: list[str]) -> str:
    src = json.loads(SRC.read_text(encoding="utf-8"))
    titles = {f["code"]: f["title"] for f in json.loads((ROOT / "data" / "fault_types.json").read_text("utf-8"))}
    by = {(c.code, c.engine): c for c in cells}
    counts: dict[str, int] = defaultdict(int)
    for c in cells:
        counts[c.status] += 1
    lines = [
        "# Матрица «код неисправности × двигатель» (issue #10)",
        "",
        f"{datetime.now():%Y-%m-%d %H:%M}. Источник: `data/fault_matrix.src.json` → `scripts/build_fault_matrix.py` → "
        "`fault_matrix.json` (data/ и INDEX_DIR, в git не входит).",
        "",
        "✅ подтверждено (узел есть, страницы и работы из руководства) · ⛔ узла нет (заявка невозможна) · "
        "📭 руководство молчит (агент: «в руководстве нет → дефектовка») · "
        "❔ применимость не ясна (заявку не блокирует).",
        "",
        "Итог: "
        + ", ".join(f"{ICON[s]} {counts[s]}" for s in ("confirmed", "not_applicable", "silent", "unknown"))
        + f" из {len(cells)}.",
        "",
        "| Код | Узел | " + " | ".join(ENGINES) + " |",
        "|---|---|" + "---|" * len(ENGINES),
    ]
    for code in sorted(src["codes"]):
        row = []
        for e in ENGINES:
            c = by[(code, e)]
            n = f"{len(c.pages)} стр./{len(c.operations)} раб."
            row.append("⛔" if c.status == "not_applicable" else f"{ICON[c.status]} {n}")
        lines.append(f"| {code} | {titles.get(code, '')} | " + " | ".join(row) + " |")
    lines += ["", "## Узла нет (⛔) — основание", ""]
    for c in cells:
        if c.status == "not_applicable" and c.basis:
            mark = " *(вывод из теххарактеристики)*" if c.inference else ""
            where = f"{c.basis.doc}, стр. {c.basis.page}"
            lines.append(f"- **{c.code} × {c.engine}** — {c.why}{mark}. {where}: «{c.basis.quote}»")
    lines += ["", "## Руководство молчит или применимость не ясна (📭, ❔)", ""]
    for c in cells:
        if c.status in ("silent", "unknown"):
            lines.append(f"- {ICON[c.status]} **{c.code} × {c.engine}**" + (f" — {c.note}" if c.note else ""))
    notes = [c for c in cells if c.note and c.status in ("confirmed", "not_applicable")]
    if notes:
        lines += ["", "## Примечания", ""] + [f"- **{c.code} × {c.engine}** — {c.note}" for c in notes]
    imp = impossible_checks(cells)
    lines += [
        "",
        f"## «Невозможные» проверки из данных: {len(imp)}",
        "",
        "| ТС | Проверка | Код | Двигатель | Почему |",
        "|---|---|---|---|---|",
        *imp,
        "",
        "## Выброшено проверкой",
        "",
        *([f"- {p}" for p in problems] or ["Ничего."]),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, default=ROOT / "reports" / f"{datetime.now():%Y-%m-%d}-matrix.md")
    args = ap.parse_args()
    path = index_dir()
    cells, problems = build(path)
    cells, more = enrich(cells, load_pages())  # запчасти с обозначениями и инструмент (issue #10, п. 2)
    problems += more
    passport = json.loads((path / "passport.json").read_text(encoding="utf-8"))
    out = save_matrix(
        {
            "_comment": "Собрано scripts/build_fault_matrix.py из data/fault_matrix.src.json и индекса. "
            "Руками не править.",
            "index": passport.get("meta", {}),
            "cells": [c.to_json() for c in cells],
        }
    )
    PARTS_REPORT.write_text(parts_report(cells), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report(cells, problems), encoding="utf-8")
    rep = args.report.relative_to(ROOT)
    print(f"{', '.join(map(str, out))}: {len(cells)} ячеек; отчёт {rep}; выброшено {len(problems)}")
    fatal = [p for p in problems if "основание" in p or "ячейки нет" in p or "без основания" in p]
    for p in fatal:
        print("ОШИБКА:", p, file=sys.stderr)
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())
