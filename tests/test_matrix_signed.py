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

from service.fault_matrix import QUOTE_MAX_WORDS, Ref, ref_problem

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
    for engine in SRC["groups"][group]:  # документ — этого двигателя, страница есть в PDF
        for ref in cell["operations"] + cell.get("safety", []):
            assert ref_problem(Ref.from_json(ref), engine, None) is None, ref


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
