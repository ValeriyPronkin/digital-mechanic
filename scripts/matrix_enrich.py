"""Запчасти с каталожным обозначением и инструмент к работам — в подтверждённые ячейки матрицы (issue #10, п. 2).

Только то, что прямо есть на странице, дословно; код сверяет (`verify_cell`):
  запчасть — строка перечня «Название Обозначение» в руководствах ЭТОГО двигателя; название (до 4 слов, с заглавной)
    называет узел кода (`must` из источника матрицы); цитата — сама строка, обозначение стоит в ней;
  инструмент — в самой фразе работы или в продолжении процедуры на той же странице (до следующей работы):
    щуп с размером, ключ S=…, динамометрический ключ, торцевая головка, съёмник, приспособление, оправка, манометр…
    Не назван — поле пустое, не догадываемся.

  uv run python scripts/matrix_enrich.py  → дополнить fault_matrix.json (data/ и INDEX_DIR) и reports/parts-tools.md
Вызывается и из scripts/build_fault_matrix.py после сборки.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path

from service.fault_matrix import Cell, Ref, matrix_path, normalize, save_matrix, verify_cell
from service.manuals.catalog import documents_for_engine
from service.manuals.index import index_dir, load_fragments

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "fault_matrix.src.json"
REPORT = ROOT / "reports" / "parts-tools.md"
MAX_DESIGNATED = 6

DESIGNATION = re.compile(r"(?<![\d.\-])(\d{3,5}[.\-]\d{7}(?:-\d{2})?)(?!\d)")
_NOT_PART = re.compile(
    r"двигател|комплект|рисун|рис\b|сопротивлен|внешн|\bвид\b|характерист|модел|исполнен|автомоб|автобус|"
    r"установ|начал|открыт|давлен|момент|размер|зазор|диаметр|номинал|частот|ремонтн|групп|таблиц",
    re.I,
)
_CUT = re.compile(r"[.;:,()\[\]–—•\d]")
TOOL = re.compile(
    r"щуп\w*(?:\s+(?:толщиной\s+)?\d+(?:[,.]\d+)?(?:\s*(?:и|или|[-–])\s*\d+(?:[,.]\d+)?)?\s*мм)?"
    r"|динамометрическ\w+\s+ключ\w*"
    r"|ключ\w*\s+(?:на|под)\s+\d+"
    r"|\(?S\s*(?:ВН|вн)?\s*=\s*\d+\)?"
    r"|торцев\w+\s+(?:головк|ключ)\w*"
    r"|съ[её]мник\w*(?:\s+И-?\d[\w.\-]*)?"
    r"|приспособлени\w*\s+(?:И-?\d[\w.\-]*|\d{3,5}[.\-]\d{4,7}[\w.\-]*)"
    r"|оправк\w*|манометр\w*|индикатор\w*(?:\s+часового\s+типа)?|микрометр\w*|нутромер\w*|штангенциркул\w*"
    r"|угломер\w*|компрессометр\w*|стробоскоп\w*|мультиметр\w*|диагностическ\w+\s+прибор\w*"
    r"|отв[её]ртк\w*|плоскогубц\w*|линейк\w*",
    re.I,
)
_OP_START = re.compile(
    r"\s(?=(?:Заменить|Отрегулировать|Проверить|Снять|Установить|Затянуть|Промыть|Устранить|Слить|Залить|"
    r"Долить|Отвернуть|Завернуть|Провернуть|Довернуть|Разобрать|Подтянуть)\b)"
)
PageText = Callable[[str, int], str | None]


def flat(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("|", " "))


def table_rows(text: str) -> list[tuple[str, str]]:
    """(название, обозначение) из строк перечня: название — до 4 слов перед номером, с заглавной."""
    out = []
    for line in flat(text).split("\n"):
        for m in DESIGNATION.finditer(line):
            seg = _CUT.split(line[: m.start()])[-1].strip()
            words = seg.split()
            if 1 <= len(words) <= 4 and words[0][:1].isupper() and len(words[0]) >= 4 and not _NOT_PART.search(seg):
                out.append((seg, m.group(1)))
    return out


def designated_parts(cell: Cell, must: re.Pattern[str], pages: dict[tuple[str, int], str]) -> list[Ref]:
    docs = {d.doc_id for d in documents_for_engine(cell.engine)}
    found: dict[str, Ref] = {}
    for (doc, page), text in sorted(pages.items()):
        if doc not in docs:
            continue
        for name, des in table_rows(text):
            if must.search(name) and des not in found:
                found[des] = Ref(doc=doc, page=page, quote=f"{name} {des}", designation=des)
    return list(found.values())[:MAX_DESIGNATED]


def tools_for(op: Ref, page_text: str) -> list[str]:
    """Инструмент из фразы работы и продолжения процедуры (до следующей работы, не дальше 400 знаков)."""
    text = re.sub(r"\s+", " ", page_text.replace("|", " "))
    pos = normalize(text).find(normalize(op.quote))
    if pos < 0:
        return []
    # normalize сохраняет длину до пробелов не точно — ищем по первым словам цитаты в исходном тексте
    head = re.escape(op.quote.split()[0]) if op.quote.split() else ""
    starts = [m.start() for m in re.finditer(head, text)] if head else []
    start = min(starts, key=lambda s: abs(s - pos)) if starts else pos
    tail = text[start : start + len(op.quote) + 400]
    nxt = _OP_START.search(tail, len(op.quote))
    scope = tail[: nxt.start()] if nxt else tail
    best: dict[str, str] = {}  # основа слова → самая подробная форма («щупом 0,1 мм», а не «щупа»)
    for m in TOOL.finditer(scope):
        t = m.group(0).strip(" ()")
        if normalize(t) not in normalize(page_text):
            continue
        key = re.sub(r"[^а-яёa-z]", "", t.lower())[:3]
        if len(t) > len(best.get(key, "")):
            best[key] = t
    return list(best.values())


def enrich(cells: list[Cell], pages: dict[tuple[str, int], str]) -> tuple[list[Cell], list[str]]:
    src = json.loads(SRC.read_text(encoding="utf-8"))["codes"]
    out: list[Cell] = []
    problems: list[str] = []

    def page_text(doc: str, page: int) -> str | None:
        return pages.get((doc, page))

    for cell in cells:
        if cell.status != "confirmed":
            out.append(cell)
            continue
        must = re.compile(src[cell.code]["must"], re.I)
        ops = [
            Ref(doc=o.doc, page=o.page, quote=o.quote, what=o.what, tools=tools_for(o, pages.get((o.doc, o.page), "")))
            for o in cell.operations
        ]
        plain = [p for p in cell.spare_parts if not p.designation]
        parts = designated_parts(cell, must, pages) + plain
        draft = Cell(**{**cell.__dict__, "operations": ops, "spare_parts": parts})
        fixed, errs = verify_cell(draft, page_text)
        problems += [f"{cell.code} × {cell.engine}: {e}" for e in errs]
        out.append(fixed)
    return out, problems


def report(cells: list[Cell]) -> str:
    conf = [c for c in cells if c.status == "confirmed"]
    by_engine: dict[str, Counter[str]] = defaultdict(Counter)
    for c in conf:
        k = by_engine[c.engine]
        k["ячеек"] += 1
        k["ячеек с обозначениями"] += any(p.designation for p in c.spare_parts)
        k["позиций с обозначением"] += sum(1 for p in c.spare_parts if p.designation)
        k["работ"] += len(c.operations)
        k["работ с инструментом"] += sum(1 for o in c.operations if o.tools)
    cols = ["ячеек", "ячеек с обозначениями", "позиций с обозначением", "работ", "работ с инструментом"]
    lines = [
        "# Запчасти с обозначениями и инструмент в матрице (issue #10, п. 2)",
        "",
        "Собрано `scripts/matrix_enrich.py` из индекса: только то, что прямо есть на странице, цитаты проверены кодом. "
        "Подтверждённые ячейки (status confirmed).",
        "",
        "| Двигатель | " + " | ".join(cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    total: Counter[str] = Counter()
    for eng in sorted(by_engine):
        total.update(by_engine[eng])
        lines.append(f"| {eng} | " + " | ".join(str(by_engine[eng][c]) for c in cols) + " |")
    lines.append("| **всего** | " + " | ".join(f"**{total[c]}**" for c in cols) + " |")
    lines += ["", "## Обозначения", ""]
    for c in conf:
        for p in c.spare_parts:
            if p.designation:
                lines.append(f"- {c.code} × {c.engine}: {p.part_name} — **{p.designation}** ({p.doc}, стр. {p.page})")
    lines += ["", "## Инструмент к работам", ""]
    for c in conf:
        for o in c.operations:
            if o.tools:
                lines.append(f"- {c.code} × {c.engine}, {o.doc} стр. {o.page}: {o.quote[:80]} → {', '.join(o.tools)}")
    return "\n".join(lines) + "\n"


def load_pages() -> dict[tuple[str, int], str]:
    pages: dict[tuple[str, int], list[str]] = defaultdict(list)
    for f in load_fragments(index_dir() / "fragments.jsonl"):
        pages[(f.doc_id, f.page)].append(f.text)
    return {k: "\n".join(v) for k, v in pages.items()}


def main() -> int:
    data = json.loads(matrix_path().read_text(encoding="utf-8"))
    cells = [Cell.from_json(d) for d in data["cells"]]
    cells, problems = enrich(cells, load_pages())
    data["cells"] = [c.to_json() for c in cells]
    out = save_matrix(data)
    REPORT.write_text(report(cells), encoding="utf-8")
    print(f"{', '.join(map(str, out))} дополнена; отчёт {REPORT.relative_to(ROOT)}; выброшено {len(problems)}")
    for p in problems:
        print("  выброшено:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
