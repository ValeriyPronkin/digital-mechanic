"""Чтение PDF: текст по страницам (pypdfium2), таблицы и таблицы неисправностей (pdfplumber).

PyMuPDF не используем: AGPL. Номер страницы — всегда номер PDF с 1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium

from .text import clean_page_text, printed_page_number

LOW_TEXT_CHARS = 50  # меньше — страница «без текста», идёт в OCR


@dataclass
class PageText:
    page: int  # номер PDF с 1
    raw: str  # как отдал pdfium (для сверки с PDF)
    text: str  # после склейки переносов
    printed: int | None  # печатный номер, если напечатан


def read_pages(path: Path) -> list[PageText]:
    pdf = pdfium.PdfDocument(str(path))
    try:
        out: list[PageText] = []
        for i in range(len(pdf)):
            page = pdf[i]
            textpage = page.get_textpage()
            raw = textpage.get_text_range()
            textpage.close()
            page.close()
            out.append(PageText(page=i + 1, raw=raw, text=clean_page_text(raw), printed=printed_page_number(raw)))
        return out
    finally:
        pdf.close()


def render_page_jpeg(path: Path, page: int, scale: float = 2.0) -> bytes:
    """Страница PDF → JPEG для OCR."""
    import io

    pdf = pdfium.PdfDocument(str(path))
    try:
        img = pdf[page - 1].render(scale=scale).to_pil()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        return buf.getvalue()
    finally:
        pdf.close()


@dataclass
class TableRow:
    symptom: str
    cause: str
    remedy: str


@dataclass
class PageTables:
    page: int
    tables: list[list[list[str]]] = field(default_factory=list)  # обычные таблицы: строки × ячейки
    fault_rows: list[TableRow] = field(default_factory=list)  # «симптом → причина → способ устранения»


_FAULT_HEADER = re.compile(r"(Способ|Метод)\s+устранения")
_CELL_WS = re.compile(r"\s+")


def _cell(s: Any) -> str:
    return clean_page_text(str(s or "")).replace("\n", " ").strip() if s else ""


def _text_in(page: Any, x0: float, y0: float, x1: float, y1: float) -> str:
    """Текст символов, чей центр внутри прямоугольника (crop берёт и задевающие края — строки слипаются)."""

    def inside(obj: dict[str, Any]) -> bool:
        if obj.get("object_type") != "char":
            return False
        cx = (obj["x0"] + obj["x1"]) / 2
        cy = (obj["top"] + obj["bottom"]) / 2
        return bool(x0 <= cx < x1 and y0 <= cy < y1)

    return _cell(page.filter(inside).extract_text())


def _clusters(values: list[float], gap: float) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > gap:
            out.append(v)
    return out


def fault_rows(page: Any, symptom: str = "") -> list[TableRow]:
    """Строки таблицы неисправностей страницы pdfplumber.

    pdfplumber не собирает эти таблицы сам: ячейки нарисованы прямоугольниками, а слова соседних
    колонок слипаются. Колонки берём по вертикальным рёбрам, строки — по горизонтальным, текст ячейки —
    символы, чей центр внутри ячейки. Строка, где заполнена только первая колонка во всю ширину, —
    заголовок-симптом («1. Двигатель не пускается») для следующих строк; symptom — последний симптом
    предыдущей страницы, если таблица продолжается.
    """
    hits = page.search(_FAULT_HEADER.pattern)
    if not hits:
        return []
    top = hits[0]["bottom"] + 1
    v_edges = [e for e in page.edges if e["orientation"] == "v" and e["bottom"] > top]
    xs = _clusters([e["x0"] for e in v_edges], gap=4)
    if len(xs) < 3:  # нужна хотя бы одна внутренняя граница колонок
        return []
    left, right = xs[0], xs[-1]
    h_edges = [
        e["top"] for e in page.edges if e["orientation"] == "h" and e["top"] > top - 2 and e["x1"] - e["x0"] > 20
    ]
    ys = _clusters([top, *h_edges, page.height], gap=3)
    rows: list[TableRow] = []
    for y0, y1 in pairwise(ys):
        if y1 - y0 < 4:
            continue
        # Внутренние границы — только те, чья вертикальная линия проходит через эту строку:
        # заголовок-симптом во всю ширину («1 ДВИГАТЕЛЬ НЕ ПУСКАЕТСЯ») линий внутри не имеет.
        inner = [
            x
            for x in xs[1:-1]
            if any(abs(e["x0"] - x) <= 4 and e["top"] < y1 - 2 and e["bottom"] > y0 + 2 for e in v_edges)
        ]
        bounds = [left, *inner, right]
        cells = [_text_in(page, a, y0, b, y1) for a, b in pairwise(bounds) if b - a > 8]
        if not any(cells):
            continue
        if _FAULT_HEADER.search(" ".join(cells)):
            continue  # шапка или её повтор на странице-продолжении
        if len(cells) < 2 or not cells[-1]:
            # строка без способа устранения — подзаголовок-симптом
            symptom = " ".join(c for c in cells if c)
            continue
        cause, remedy = cells[-2], cells[-1]
        if len(cells) >= 3 and cells[-3]:
            symptom = cells[-3]
        rows.append(TableRow(symptom=symptom, cause=cause, remedy=remedy))
    return rows if _rows_look_sane(rows) else []


def _rows_look_sane(rows: list[TableRow]) -> bool:
    """Отбраковка разбора: в части PDF строки таблицы не разделены линиями (одна строка на страницу)
    или линия под каждой строкой текста (ячейка рвётся на куски). Тогда страница остаётся текстом."""
    if len(rows) < 2:
        return False
    mean = sum(len(r.cause) + len(r.remedy) for r in rows) / len(rows)
    longest = max(len(r.cause) + len(r.remedy) for r in rows)
    # Колонка разрезана посреди слова: причина кончается буквой, способ начинается со строчной
    torn = sum(1 for r in rows if r.cause[-1:].isalpha() and r.remedy[:1].islower()) / len(rows)
    return 50 <= mean and longest <= 1500 and torn <= 0.3


def read_tables(path: Path, pages: list[int] | None = None) -> list[PageTables]:
    """Таблицы по страницам. pages — какие страницы смотреть (по умолчанию все)."""
    out: list[PageTables] = []
    with pdfplumber.open(str(path)) as pdf:
        numbers = pages or list(range(1, len(pdf.pages) + 1))
        last_symptom, last_page = "", -1
        for n in numbers:
            page = pdf.pages[n - 1]
            rec = PageTables(page=n)
            try:
                rec.fault_rows = fault_rows(page, last_symptom if n == last_page + 1 else "")
                if rec.fault_rows:
                    last_symptom, last_page = rec.fault_rows[-1].symptom, n
                if not rec.fault_rows:
                    for t in page.extract_tables():
                        rows = [[_cell(c) for c in row] for row in t]
                        rows = [r for r in rows if any(r)]
                        if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                            rec.tables.append(rows)
            except Exception:  # noqa: S112  # битая разметка одной страницы не валит сборку
                continue
            finally:
                page.close()
            if rec.tables or rec.fault_rows:
                out.append(rec)
    return out
