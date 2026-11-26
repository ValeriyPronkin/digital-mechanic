"""Приёмка на собранном индексе (`make index`). В CI индекса нет — тесты пропускаются;
локально и на стенде проверяют фильтр по двигателю на реальных руководствах."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from service.manuals.catalog import documents_for_engine
from service.manuals.search import ManualIndex

INDEX = Path(os.environ.get("INDEX_DIR", ".index"))
pytestmark = pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")

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


@pytest.fixture(scope="module")
def index() -> ManualIndex:
    return ManualIndex.load(INDEX, semantic=False)  # без сети: фильтр проверяем на BM25


@pytest.mark.parametrize("engine", ENGINES)
def test_no_foreign_engine_documents(index: ManualIndex, engine: str) -> None:
    allowed = {d.doc_id for d in documents_for_engine(engine)}
    for q in QUERIES:
        hits = index.search(q, engine)
        assert hits, (q, engine)
        assert {h.fragment.doc_id for h in hits} <= allowed, (q, engine)


@pytest.mark.parametrize(("engine", "prefix"), [("ЯМЗ-236М2", "yamz-236"), ("ЗМЗ-5234.10", "zmz-5234")])
def test_valve_clearance(index: ManualIndex, engine: str, prefix: str) -> None:
    hits = index.search("тепловой зазор клапанов", engine)
    assert hits and all(h.fragment.doc_id.startswith(prefix) for h in hits)
