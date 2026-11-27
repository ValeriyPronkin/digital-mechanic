"""F01 × ЯМЗ-236М2 (видео B418HK98 / S-0009): ячейка правлена вручную в data/fault_matrix.json (#148-lite) —
пересборка build_fault_matrix её перезапишет, пока логика подписанных ячеек (#124) не перенесена.
Таблица неисправностей РЭ стр. 53 — первой; работы заявки — без «обкатки» и спорного срока «15 мин»."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from service.fault_matrix import normalize

MATRIX = Path(__file__).resolve().parents[1] / "data" / "fault_matrix.json"
INDEX = Path(os.environ.get("INDEX_DIR", ".index"))


def _cell() -> dict:
    cells = json.loads(MATRIX.read_text(encoding="utf-8"))["cells"]
    return next(c for c in cells if c["code"] == "F01" and c["engine"] == "ЯМЗ-236М2")


def test_fault_table_page_first_and_works_without_running_in() -> None:
    cell = _cell()
    assert cell["status"] == "confirmed"
    assert (cell["pages"][0]["doc"], cell["pages"][0]["page"]) == ("yamz-236-re", 53)
    assert (cell["basis"]["doc"], cell["basis"]["page"]) == ("yamz-236-re", 53)
    works = [o["quote"] for o in cell["operations"]]
    assert works and all("обкатк" not in w and "15 мин" not in w for w in works)
    assert all("обкатк" not in p["quote"] and "15 мин" not in p["quote"] for p in cell["pages"])


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_quotes_are_on_their_pages_in_real_index() -> None:
    from service.manual_search import default_searcher

    page_text = default_searcher().page_text
    cell = _cell()
    for ref in [cell["basis"], *cell["pages"], *cell["operations"]]:
        text = page_text(ref["doc"], ref["page"])
        assert text and normalize(ref["quote"]) in normalize(text), (ref["doc"], ref["page"], ref["quote"])
