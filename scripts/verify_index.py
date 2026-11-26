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
import random
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber

from service.manuals.catalog import DOCS_BY_ID, documents_for_engine
from service.manuals.index import manuals_dir
from service.manuals.lexical import tokenize
from service.manuals.search import ManualIndex

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


def verify_pages(index: ManualIndex, lines: list[str]) -> bool:
    by_page: dict[tuple[str, int], list[str]] = defaultdict(list)
    for f in index.fragments:
        if f.source == "текст":
            by_page[(f.doc_id, f.page)].append(f.text)
    keys = sorted(by_page)
    sample = random.Random(SEED).sample(keys, SAMPLE)  # noqa: S311  # выборка для сверки, не криптография
    ok_all = True
    lines += [
        "## 1. Выборка 20 страниц: номер и текст",
        "",
        "Текст индекса для страницы N сравнивается со словами pdfplumber на страницах N−1, N, N+1.",
        "",
        "| Документ | Стр. PDF | Совпадение слов: N−1 / **N** / N+1 | Итог |",
        "|---|---|---|---|",
    ]
    src = manuals_dir()
    opened: dict[str, Any] = {}
    for doc_id, page in sorted(sample):
        pdf = opened.setdefault(doc_id, pdfplumber.open(str(src / DOCS_BY_ID[doc_id].file)))
        ours = _words("\n".join(by_page[(doc_id, page)]))
        scores = []
        for p in (page - 1, page, page + 1):
            if 1 <= p <= len(pdf.pages):
                scores.append(_overlap(ours, _words(pdf.pages[p - 1].extract_text() or "")))
            else:
                scores.append(0.0)
        ok = scores[1] >= 0.8 and scores[1] > max(scores[0], scores[2])
        ok_all &= ok
        cells = f"{scores[0]:.2f} / **{scores[1]:.2f}** / {scores[2]:.2f}"
        lines.append(f"| {doc_id} | {page} | {cells} | {'✅' if ok else '❌'} |")
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
