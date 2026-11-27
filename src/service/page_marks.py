"""Подсветка строки на картинке страницы руководства (приём Никиты `app/page_marks.py`, issue #52).

Строки страницы собираются из текстового слоя PDF: символы идут в порядке вывода, а не чтения, поэтому строка —
символы с одной высотой, по горизонтали. Рамка — в долях сторон картинки, от левого верхнего угла (как `PageMark`
интерфейса). На стенде PDF нет (D-9): строки собираются локально и лежат в бакете `marks/<doc_id>.json`.

Неверная отметка хуже никакой. Строка отмечается, только если на странице ровно одна такая:
- строка совпадает с цитатой (без пробелов, после нормализации); иначе
- строка содержит цитату целиком (таблица в тексте страницы порвана иначе, чем в печати); иначе
- строка — бо́льшая часть цитаты и в ней все числа цитаты (к строке в тексте приклеилась соседняя ячейка); иначе
- цитата — предложение, перенесённое на 2–4 строки печати: кратчайший ряд соседних строк, содержащий её целиком;
  рамка обводит этот ряд.
Повёрнутые страницы не размечаются.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 — доли ширины и высоты картинки, от левого верхнего угла

_DASHES = str.maketrans(
    {"–": "-", "—": "-", "−": "-", "‐": "-", "ё": "е", "Ё": "е", "«": "", "»": "", '"': "", "\ufffe": "", "\u00ad": ""}
)
_SPACE = re.compile(r"\s+")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_MIN_PART = 8  # цитата или строка короче — слишком мало, чтобы отличить её от соседних
_MOST = 0.6  # доля цитаты, которую должна покрыть строка без её хвоста
_MAX_RUN = 4  # предложение длиннее четырёх строк печати не обводим: рамка на полстраницы ничего не показывает


def key(text: str) -> str:
    """Без пробелов и дефисов: перенос «креп-/ления» и тире списка не мешают сравнению (числа сверяются отдельно)."""
    return _SPACE.sub("", text.translate(_DASHES).lower()).replace("-", "")


def numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUM.findall(text)}


def page_lines(pdf_path: Path) -> dict[int, list[dict[str, Any]]]:
    """Строки каждой страницы PDF (страница с 1): текст и рамка в долях. Повёрнутые страницы — без строк."""
    import pypdfium2 as pdfium

    out: dict[int, list[dict[str, Any]]] = {}
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for n in range(len(pdf)):
            page = pdf[n]
            if page.get_rotation() % 360:
                out[n + 1] = []
                continue
            w, h = page.get_size()
            tp = page.get_textpage()
            lines: list[dict[str, Any]] = []
            for i in range(tp.count_chars()):
                ch = tp.get_text_range(i, 1)
                if ch in ("\r", "\n", ""):
                    continue
                left, bottom, right, top = tp.get_charbox(i)
                if right <= left or top <= bottom:
                    continue
                # символ — в строке, если его высота наполовину лежит в полосе строки, а мелкий знак (запятая ниже
                # линии букв, дефис) — если его середина рядом с полосой: так они не отрываются в отдельные «строки»
                ht = top - bottom
                line = next(
                    (
                        ln
                        for ln in lines
                        if min(top, ln["top"]) - max(bottom, ln["bottom"]) > 0.5 * min(ht, ln["top"] - ln["bottom"])
                        or (
                            ln["bottom"] - 0.25 * (ln["top"] - ln["bottom"])
                            <= (top + bottom) / 2
                            <= ln["top"] + 0.25 * (ln["top"] - ln["bottom"])
                            and ht < 0.6 * (ln["top"] - ln["bottom"])  # мелкий знак (запятая, дефис) у своей строки
                        )
                    ),
                    None,
                )
                if line is None:
                    line = {"top": top, "bottom": bottom, "chars": []}
                    lines.append(line)
                elif not ch.isspace() and ht >= 0.6 * (line["top"] - line["bottom"]):
                    line["top"], line["bottom"] = max(line["top"], top), min(line["bottom"], bottom)
                line["chars"].append((left, bottom, right, top, ch))
            page_out = []
            for ln in sorted(lines, key=lambda x: -(x["top"] + x["bottom"])):
                chars = sorted(ln["chars"])
                text = "".join(c[4] for c in chars)
                ink = [c for c in chars if not c[4].isspace()]
                if not ink or not text.strip():
                    continue
                x0, x1 = min(c[0] for c in ink), max(c[2] for c in ink)
                y_top, y_bottom = max(c[3] for c in ink), min(c[1] for c in ink)
                box = [round(x0 / w, 4), round((h - y_top) / h, 4), round(x1 / w, 4), round((h - y_bottom) / h, 4)]
                page_out.append({"t": text.strip(), "b": box})
            out[n + 1] = page_out
    finally:
        pdf.close()
    return out


def find_mark(lines: list[dict[str, Any]], quote: str) -> Box | None:
    """Рамка строки с цитатой — только если на странице она одна (см. модуль). Иначе None."""
    q = key(quote)
    if len(q) < 4:
        return None
    keyed = [(key(ln["t"]), ln) for ln in lines]
    qnums = numbers(quote)
    tiers = [
        [ln for k, ln in keyed if k == q],
        [ln for k, ln in keyed if len(q) >= _MIN_PART and q in k],
        [
            ln
            for k, ln in keyed
            if qnums and len(k) >= _MIN_PART and k in q and len(k) >= _MOST * len(q) and qnums <= numbers(ln["t"])
        ],
    ]
    for found in tiers:
        if len(found) == 1:
            b = found[0]["b"]
            return (b[0], b[1], b[2], b[3])
        if len(found) > 1:
            return None  # несколько одинаковых строк — не угадываем
    if len(q) < _MIN_PART and qnums:
        # Короткая цитата с числом («15 мин» — чип ответа о сроке на стр. 269, demo-check 27.11): рамка, если на
        # странице она ровно в одной строке и число там то же. Без числа короткое не обводим — слишком похоже.
        found = [ln for k, ln in keyed if q in k and qnums <= numbers(ln["t"])]
        if len(found) == 1:
            b = found[0]["b"]
            return (b[0], b[1], b[2], b[3])
        return None
    return _run_mark([(k, ln) for k, ln in keyed if k], q) if len(q) >= 2 * _MIN_PART else None


def _run_mark(keyed: list[tuple[str, dict[str, Any]]], q: str) -> Box | None:
    """Кратчайший ряд из 2–4 соседних строк, в котором цитата целиком; только если такой ряд на странице один."""
    runs = []
    for i in range(len(keyed)):
        for n in range(2, _MAX_RUN + 1):
            part = keyed[i : i + n]
            if len(part) < n:
                break
            if q in "".join(k for k, _ in part):
                # без первой или последней строки цитата уже не помещается — ряд кратчайший
                if q not in "".join(k for k, _ in part[1:]) and q not in "".join(k for k, _ in part[:-1]):
                    runs.append(part)
                break
    if len(runs) != 1:
        return None
    boxes = [ln["b"] for _, ln in runs[0]]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


class PageMarks:
    """Строки страниц по документам: память экземпляра → бакет `marks/<doc>.json` → локальный PDF."""

    def __init__(self, bucket: Any = None) -> None:
        self.bucket = bucket
        self._docs: dict[str, dict[int, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    def lines(self, doc_id: str, page: int) -> list[dict[str, Any]]:
        with self._lock:
            doc = self._docs.get(doc_id)
        if doc is None:
            doc = self._load(doc_id)
            with self._lock:
                self._docs[doc_id] = doc
        return doc.get(page, [])

    def _load(self, doc_id: str) -> dict[int, list[dict[str, Any]]]:
        if self.bucket is not None:
            try:
                raw = json.loads(self.bucket.get(f"marks/{doc_id}.json"))
                return {int(k): v for k, v in raw.items()}
            except Exception as exc:
                log.warning("marks/%s.json не прочитан: %s", doc_id, type(exc).__name__)
        from service.manual_search import manual_pdf

        path = manual_pdf(doc_id)
        return page_lines(path) if path is not None else {}

    def mark(self, doc_id: str, page: int, quote: str | None) -> Box | None:
        if not quote:
            return None
        return find_mark(self.lines(doc_id, page), quote)


def main(argv: list[str] | None = None) -> int:
    """`python -m service.page_marks publish` — собрать строки по локальным PDF и выложить в бакет marks/."""
    import argparse

    import httpx

    from service import kb_store
    from service.manual_search import manual_pdf
    from service.manuals.catalog import DOCUMENTS

    p = argparse.ArgumentParser(prog="python -m service.page_marks")
    p.add_argument("cmd", choices=["publish", "build"])
    p.add_argument("--out", type=Path, default=Path(".state/marks"))
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120) as http:
        bucket = kb_store._env_bucket(http, allow_static=True) if args.cmd == "publish" else None
        for doc in DOCUMENTS:
            path = manual_pdf(doc.doc_id)
            if path is None:
                print(f"{doc.doc_id}: нет PDF — пропуск")
                continue
            data = page_lines(path)
            body = json.dumps({str(k): v for k, v in data.items()}, ensure_ascii=False).encode("utf-8")
            (args.out / f"{doc.doc_id}.json").write_bytes(body)
            lines = sum(len(v) for v in data.values())
            if bucket is not None:
                bucket.put(f"marks/{doc.doc_id}.json", body, "application/json")
            print(f"{doc.doc_id}: страниц {len(data)}, строк {lines}, {len(body) // 1024} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
