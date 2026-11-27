"""Ячейки матрицы, которые подписанный инженером реестр покрытия называет покрытыми (registry/coverage.yaml,
V Pronkin, 27.11), а сборка по поиску считала «молчащими»: страницы и работы — из источника, не из поиска.

Стенд 27.11: на F03 × ЯМЗ-236М2 основанием стояла таблица генератора (РЭ стр. 57), на F02 — РЭ стр. 53 без единой
работы, хотя строка «Неисправен манометр — Заменить исправным» на ней есть. Агент говорил «в руководстве нет»."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from build_fault_matrix import ANCHOR_WORDS
from matrix_fixture import needs_matrix
from service.fault_matrix import QUOTE_MAX_WORDS, Ref, normalize, ref_problem

ROOT = Path(__file__).resolve().parents[1]
SRC = json.loads((ROOT / "data" / "fault_matrix.src.json").read_text(encoding="utf-8"))
INDEX = Path(os.environ.get("INDEX_DIR", ".index"))

# (код, группа источника) → (документ, первая страница): первая страница ячейки в реестре покрытия
SIGNED = {
    ("F02", "ЯМЗ-236М2"): ("yamz-236-re", 53),
    ("F03", "ЯМЗ-236М2"): ("yamz-236-re", 54),
    ("F04", "ЯМЗ-236М2"): ("yamz-236-re", 28),
    ("F07", "ЯМЗ-236М2"): ("yamz-236-re", 66),
    ("F08", "ЯМЗ-236М2"): ("yamz-236-re", 52),
    ("F04", "ЯМЗ-536"): ("yamz-536-re", 104),
    ("F12", "ЗМЗ-5234.10"): ("zmz-5234-rk", 52),
    ("F13", "ЗМЗ-409"): ("zmz-409-rk", 102),
}


def _quotes(o: object) -> list[str]:
    if isinstance(o, dict):
        return [v for k, v in o.items() if k == "quote"] + [q for k, v in o.items() if k != "quote" for q in _quotes(v)]
    if isinstance(o, list):
        return [q for v in o for q in _quotes(v)]
    return []


@pytest.mark.parametrize(("code", "group"), sorted(SIGNED))
def test_signed_cell_lists_registry_pages_and_operations(code: str, group: str) -> None:
    cell = SRC["codes"][code]["cells"][group]
    assert cell["applicable"] == "true" and cell["signed"]
    assert (cell["pages"][0]["doc"], cell["pages"][0]["page"]) == SIGNED[(code, group)]
    assert len(cell["operations"]) >= 4
    for row in cell["operations"] + cell.get("safety", []):
        # в git — только якорь строки, не её текст (#96): не больше 7 слов на строку
        assert "quote" not in row and row["words"] >= len(re.findall(r"\w+", row["anchor"]))
        assert len(re.findall(r"\w+", row["anchor"] + " " + row.get("last", ""))) <= ANCHOR_WORDS
        for engine in SRC["groups"][group]:  # документ — этого двигателя, страница есть в PDF
            assert ref_problem(Ref(doc=row["doc"], page=row["page"], quote=row["anchor"]), engine, None) is None


def test_anchor_expands_to_the_line_on_the_page() -> None:
    """Якорь разворачивается в строку страницы дословно; из двух вхождений начала — то, где строка в `words` слов
    кончается `last` (на стыке фрагментов строка повторяется)."""
    from build_fault_matrix import expand_anchor

    page = "Подтекание по кольцам гильз\nПодтекание по кольцам гильз | Заменить неисправные кольца. Трещины"
    row = {"anchor": "Подтекание по", "last": "неисправные кольца", "words": 7}
    assert expand_anchor(row, page) == "Подтекание по кольцам гильз Заменить неисправные кольца"
    assert expand_anchor({"anchor": "Трещины", "words": 1}, page) == "Трещины"
    assert expand_anchor({"anchor": "Заменить прокладку", "words": 2}, page) is None


def test_source_quotes_stay_short() -> None:
    """Открытый репозиторий (#96): цитата — не длиннее 24 слов подряд, отрывков в файле — не больше 120."""
    quotes = _quotes(SRC)
    assert len(quotes) <= 120
    assert max(len(re.findall(r"\w+", q)) for q in quotes) <= QUOTE_MAX_WORDS


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_signed_cells_build_confirmed_with_registry_pages() -> None:
    """На собранном индексе: каждая цитата работы — на своей странице, ячейка «подтверждена», первая страница — из
    реестра, ничего не выброшено проверкой."""
    from build_fault_matrix import build

    cells, problems = build(INDEX)
    by = {(c.code, c.engine): c for c in cells}
    for (code, group), first in SIGNED.items():
        for engine in SRC["groups"][group]:
            cell = by[(code, engine)]
            assert cell.status == "confirmed", (code, engine)
            assert (cell.pages[0].doc, cell.pages[0].page) == first
            assert len(cell.operations) == len(SRC["codes"][code]["cells"][group]["operations"])
            assert not [p for p in problems if p.startswith(f"{code} × {engine}:")]


def test_page_quote_starts_at_cell_and_stays_within_words() -> None:
    """Цитата страницы не режет слово («чина Способ…» на стенде 27.11): начало — у ячейки, строки с заглавной или
    предложения рядом с узлом, конец — на границе слова; не длиннее 24 слов; подстрока страницы."""
    from build_fault_matrix import flat, window

    must = re.compile("температур", re.I)
    table = (
        "Таблица 5\nПричина | Способ устранения\nПовышенная температура в системе охлаждения | Заменить термостат. Ещё"
    )
    assert window(table, must) == "Повышенная температура в системе охлаждения Заменить термостат."
    wrapped = "6. При работе следить за\nтемпературой жидкости; " + " ".join(["слово"] * 40)
    quote = window(wrapped, must)
    assert quote.startswith("При работе") and quote in flat(wrapped)  # перенос строки со строчной — не начало
    prose = " ".join(f"слово{i}" for i in range(60)) + " температура " + " ".join(f"хвост{i}" for i in range(60))
    quote = window(prose, must)
    assert quote.startswith("температура ")  # начала ячейки рядом нет — с самого слова узла
    assert len(re.findall(r"\w+", quote)) == QUOTE_MAX_WORDS
    assert all(w in prose.split() for w in quote.split())  # ни одного обрезка слова


def _at_word_bounds(quote: str, page: str) -> bool:
    q = normalize(quote)
    for m in re.finditer(re.escape(q), page):
        before = page[m.start() - 1] if m.start() else " "
        after = page[m.end()] if m.end() < len(page) else " "
        if not re.match(r"\w", before) and not re.match(r"\w", after):
            return True
    return False


@needs_matrix
@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_stored_quotes_do_not_start_or_end_inside_a_word() -> None:
    """Каждая цитата матрицы (основание, страницы, работы, запчасти, предупреждения) на своей странице стоит
    целыми словами: слева и справа от неё на странице — не буква и не цифра."""
    from service.fault_matrix import all_cells
    from service.manuals.index import load_fragments

    texts: dict[tuple[str, int], list[str]] = {}
    for f in load_fragments(INDEX / "fragments.jsonl"):
        texts.setdefault((f.doc_id, f.page), []).append(f.text)
    pages = {k: normalize("\n".join(v)) for k, v in texts.items()}
    bad = [
        (c.code, c.engine, r.page, r.quote[:40])
        for c in all_cells()
        for r in c.refs()
        if not _at_word_bounds(r.quote, pages.get((r.doc, r.page), ""))
    ]
    assert not bad, bad[:10]
