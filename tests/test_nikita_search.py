"""Поиск по документам из прототипа Никиты (SEARCH_ENGINE=nikita) над нашим индексом."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from service.manual_search import IndexSearcher, NikitaSearcher, default_searcher, search_engine
from service.nikita import search as nikita
from service.nikita.pages import other_variant

INDEX = Path(os.environ.get("INDEX_DIR", ".index"))
needs_index = pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")


def test_default_engine_is_ours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEARCH_ENGINE", raising=False)
    assert search_engine() == "ours"


def test_glossary_adds_terms_at_half_weight() -> None:
    terms = nikita.query_terms("ГБЦ течёт")
    assert terms["гбц"] == 1.0 and terms["головка"] == nikita.EXPANSION_WEIGHT


def test_page_scope_marks_other_variant() -> None:
    assert other_variant("ЗМЗ-40904.10", "zmz-409-rk", 68)  # раздел ЗМЗ-40905.10
    assert other_variant("ЗМЗ-40905.10", "zmz-409-rk", 68) is None


@needs_index
def test_nikita_searcher_over_our_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_ENGINE", "nikita")
    s = default_searcher()
    assert isinstance(s, NikitaSearcher) and isinstance(s, IndexSearcher)
    hits = s.search("момент затяжки гаек стоек осей коромысел", "ЯМЗ-236М2", k=5)
    assert hits and all(h.manual_id.startswith("yamz-236") for h in hits)  # только руководства двигателя
    assert 286 in {h.pdf_page for h in hits if h.manual_id == "yamz-236-rk"}  # приложение моментов затяжки
    vent = s.search("вентиляция картера зимой", "ЗМЗ-40904.10", k=10)
    assert not {68, 69, 70} & {h.pdf_page for h in vent}  # страницы ЗМЗ-40905.10 — вне индекса 40904
