"""Сверка собранного индекса руководств с PDF и проверка фильтра по двигателю (приёмка issue #3).

1. Выборка 20 страниц (детерминированная): текст фрагментов страницы N — из страницы N PDF.
   Независимая сверка: тот же текст другим извлекателем (pdfplumber) на той же странице совпадает по словам,
   а на соседних страницах — заметно хуже (номер страницы не сдвинут).
2. 10 запросов × 4 двигателя: в выдаче 0 документов чужих двигателей.
3. «тепловой зазор клапанов»: ЯМЗ-236М2 → руководства ЯМЗ-236, ЗМЗ-5234.10 → ЗМЗ-5234.

  uv run --env-file .env python scripts/verify_index.py [--report reports/index-verify.md]
Код возврата 1 — что-то не сошлось.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium

from service.manuals.catalog import DOCS_BY_ID, documents_for_engine
from service.manuals.index import index_dir, manuals_dir
from service.manuals.lexical import tokenize
from service.manuals.search import ManualIndex
from service.manuals.text import clean_page_text, printed_page_number

ENGINES = ("ЯМЗ-236М2", "ЯМЗ-536", "ЗМЗ-5234.10", "ЗМЗ-40904.10")
QUERIES = (
    "тепловой зазор клапанов",
    "давление масла в двигателе",
    "замена масляного фильтра",
    "двигатель не пускается",
    "момент затяжки болтов головки цилиндров",
    "натяжение ремня привода генератора",
    "перегрев двигателя причины",
    "замена охлаждающей жидкости",
    "порядок работы цилиндров",
    "периодичность технического обслуживания ТО-2",
)
SAMPLE = 20
SEED = 3


def _words(text: str) -> set[str]:
    return {t for t in tokenize(text) if len(t) > 2 and not t[0].isdigit()}


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(1, len(a))


def _bag(text: str) -> Counter[str]:
    return Counter(re.findall(r"\w+", text.lower()))


def _bag_sim(a: Counter[str], b: Counter[str]) -> float:
    """Сходство мультимножеств слов и чисел: не зависит от порядка чтения, но различает номера шагов."""
    return sum((a & b).values()) / max(1, sum((a | b).values()))


def _readable(text: str) -> bool:
    """pdfplumber рвёт повёрнутые страницы на буквы: «О б о з н а ч е н и е» — такой эталон не годится."""
    words = re.findall(r"\w+", text)
    return bool(words) and sum(len(w) for w in words) / len(words) >= 3


def verify_pages(index: ManualIndex, lines: list[str]) -> bool:
    by_page: dict[tuple[str, int], list[str]] = defaultdict(list)
    for f in index.fragments:
        if f.source == "текст":
            by_page[(f.doc_id, f.page)].append(f.text)
    keys = sorted(by_page)
    sample = random.Random(SEED).sample(keys, SAMPLE)  # noqa: S311  # выборка для сверки, не криптография
    passport = {d["doc_id"]: d for d in json.loads((index_dir() / "passport.json").read_text("utf-8"))["documents"]}
    ok_all = True
    lines += [
        "## 1. Выборка 20 страниц: номер и текст",
        "",
        "- **Номер:** печатный номер на странице PDF N равен N + смещение из паспорта; где номер не напечатан —",
        "  текст страницы N совпадает с эталоном лучше, чем N−1 и N+1.",
        "- **Текст:** доля слов индекса, найденных в тексте той же страницы другим извлекателем (pdfplumber);",
        "  если pdfplumber страницу не читает (повёрнутая таблица) — в сыром тексте pdfium. Порог 0,8.",
        "",
        "| Документ | Стр. PDF | Печатный | Номер | Слова: N−1 / **N** / N+1 | Эталон | Итог |",
        "|---|---|---|---|---|---|---|",
    ]
    src = manuals_dir()
    opened: dict[str, Any] = {}
    for doc_id, page in sorted(sample):
        doc = DOCS_BY_ID[doc_id]
        pdf = opened.setdefault(doc_id, pdfplumber.open(str(src / doc.file)))
        ours = _words("\n".join(by_page[(doc_id, page)]))
        ref_texts = [
            (pdf.pages[p - 1].extract_text() or "") if 1 <= p <= len(pdf.pages) else ""
            for p in (page - 1, page, page + 1)
        ]
        scores = [_overlap(ours, _words(t)) for t in ref_texts]
        raw_doc = pdfium.PdfDocument(str(src / doc.file))
        raw = raw_doc[page - 1].get_textpage().get_text_range()
        raw_doc.close()
        reference = "pdfplumber"
        if not _readable(ref_texts[1]):
            scores = [float("nan"), _overlap(ours, _words(clean_page_text(raw))), float("nan")]
            reference = "pdfium (pdfplumber не читает)"
        offset = passport[doc_id]["printed_minus_pdf"]
        printed = printed_page_number(raw) if offset is not None else None
        if printed is not None and offset is not None:
            number_ok = printed == page + offset
        else:
            # номер не напечатан: слова и числа страницы N ближе к эталону N, чем к N−1 и N+1
            ours_bag = _bag(clean_page_text(raw))
            ratios = [_bag_sim(ours_bag, _bag(clean_page_text(t))) for t in ref_texts]
            number_ok = ratios[1] >= 0.5 and ratios[1] > max(ratios[0], ratios[2])
        text_ok = scores[1] >= 0.8
        ok = number_ok and text_ok
        ok_all &= ok
        cells = " / ".join("—" if x != x else (f"**{x:.2f}**" if i == 1 else f"{x:.2f}") for i, x in enumerate(scores))
        lines.append(
            f"| {doc_id} | {page} | {printed if printed is not None else '—'} | {'✅' if number_ok else '❌'} "
            f"| {cells} | {reference} | {'✅' if ok else '❌'} |"
        )
    for pdf in opened.values():
        pdf.close()
    lines.append("")
    return ok_all


def verify_engines(index: ManualIndex, lines: list[str]) -> bool:
    lines += [
        "## 2. 10 запросов × 4 двигателя: чужие руководства в топ-5",
        "",
        f"Поиск: {'слова + смысл' if index.semantic else 'только слова'}.",
        "",
        "| Запрос | " + " | ".join(ENGINES) + " |",
        "|---|" + "---|" * len(ENGINES),
    ]
    foreign_total = 0
    for q in QUERIES:
        cells = []
        for eng in ENGINES:
            allowed = {d.doc_id for d in documents_for_engine(eng)}
            hits = index.search(q, eng)
            foreign = [h for h in hits if h.fragment.doc_id not in allowed]
            foreign_total += len(foreign)
            pages = ", ".join(f"{h.fragment.doc_id.split('-')[-1]}:{h.fragment.page}" for h in hits)
            cells.append(("❌ " if foreign else "") + (pages or "—"))
        lines.append(f"| {q} | " + " | ".join(cells) + " |")
    lines += ["", f"**Чужих документов в выдаче: {foreign_total}** (из {len(QUERIES) * len(ENGINES) * 5} мест).", ""]
    return foreign_total == 0


def verify_valve(index: ManualIndex, lines: list[str]) -> bool:
    lines += ["## 3. «тепловой зазор клапанов»", ""]
    ok_all = True
    for eng, prefix in (("ЯМЗ-236М2", "yamz-236"), ("ЗМЗ-5234.10", "zmz-5234")):
        hits = index.search("тепловой зазор клапанов", eng)
        ok = bool(hits) and all(h.fragment.doc_id.startswith(prefix) for h in hits)
        ok_all &= ok
        lines.append(f"**{eng}** {'✅' if ok else '❌'}")
        lines.append("")
        for h in hits:
            quote = re.sub(r"\s+", " ", h.quote)[:220]
            lines.append(f"- {h.fragment.designation}, стр. {h.fragment.page} · {h.fragment.section} — «{quote}»")
        lines.append("")
    return ok_all


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, default=Path("reports/index-verify.md"))
    args = ap.parse_args()
    index = ManualIndex.load()
    lines = [
        "# Сверка индекса руководств (issue #3)",
        "",
        f"{datetime.now():%Y-%m-%d %H:%M}, фрагментов {len(index.fragments)}. Скрипт: `scripts/verify_index.py`.",
        "",
    ]
    results = {
        "страницы": verify_pages(index, lines),
        "чужие двигатели": verify_engines(index, lines),
        "тепловой зазор": verify_valve(index, lines),
    }
    lines += ["## Итог", ""] + [f"- {k}: {'✅' if v else '❌'}" for k, v in results.items()]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(f"{k}: {'OK' if v else 'FAIL'}" for k, v in results.items()))
    print(f"Отчёт: {args.report}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
