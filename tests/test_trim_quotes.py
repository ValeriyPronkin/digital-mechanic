"""Цитаты руководств в данных — ссылки, не выгрузки (#96): не длиннее QUOTE_MAX_WORDS слов подряд и стоят на той
же странице, что и полная цитата."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from service.fault_matrix import QUOTE_MAX_WORDS, normalize, trim_quote

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"\w+")  # так считает слова проверка открытого репозитория


def _quotes(o: Any) -> list[str]:
    if isinstance(o, dict):
        return [v for k, v in o.items() if k == "quote" and isinstance(v, str)] + [
            q for k, v in o.items() if k != "quote" for q in _quotes(v)
        ]
    if isinstance(o, list):
        return [q for v in o for q in _quotes(v)]
    return []


def test_quotes_in_data_are_short() -> None:
    for name in ("contradictions.json",):  # матрица — база знаний, уходит из репозитория (#96, шаг 2)
        quotes = _quotes(json.loads((ROOT / "data" / name).read_text(encoding="utf-8")))
        assert quotes, name
        long = [q for q in quotes if len(WORD.findall(q)) > QUOTE_MAX_WORDS]
        assert not long, f"{name}: {len(long)} цитат длиннее {QUOTE_MAX_WORDS} слов (scripts/trim_quotes.py)"


def test_a_short_quote_is_kept_as_is() -> None:
    q = "Отрегулировать зазоры между клапанами и коромыслами."
    assert trim_quote(q) == q


def test_a_long_quote_is_cut_from_itself_and_keeps_the_numbers() -> None:
    q = " ".join(["слово"] * 30) + " момент 421-461 Н·м (43-47 кгс·м)"
    s = trim_quote(q, limit=10)
    assert len(WORD.findall(s)) <= 10
    assert normalize(s) in normalize(q)  # отрывок стоит на той же странице, что и цитата
    assert "421-461" in s and s.endswith("кгс·м")  # числа и единица в конце


def test_the_designation_stays_in_the_quote() -> None:
    q = "Подшипник шариковый радиальный 236-1006043 " + " ".join(["в", "сборе", "с", "кольцом"] * 8)
    s = trim_quote(q, keep="236-1006043", limit=8)
    assert "236-1006043" in s and normalize(s) in normalize(q)
