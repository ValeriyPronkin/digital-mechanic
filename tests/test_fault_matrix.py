"""Матрица «код × двигатель» (issue #10): полнота, доказательства, совместимость, заявка на невозможных проверках."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import pytest

from matrix_fixture import needs_matrix, write_synthetic
from service import fault_matrix
from service.compat import check, is_compatible
from service.fault_matrix import Cell, Ref, matrix_loaded, matrix_path, normalize, verify_cell
from service.manuals.catalog import ENGINES, documents_for_engine

ROOT = Path(__file__).resolve().parents[1]
# Настоящая матрица — вне git (#96): в CI её нет, тесты её содержания пропускаются (needs_matrix).
DATA = json.loads(matrix_path().read_text(encoding="utf-8")) if matrix_loaded() else {"cells": []}
CELLS = [Cell.from_json(c) for c in DATA["cells"]]
CODES = [f["code"] for f in json.loads((ROOT / "data" / "fault_types.json").read_text(encoding="utf-8"))]
SRC = json.loads((ROOT / "data" / "fault_matrix.src.json").read_text(encoding="utf-8"))

# 7 «невозможных» проверок из data/vehicles.json: узла у двигателя нет по руководству
IMPOSSIBLE = {
    ("S-0021", "F14", "ЯМЗ-236М2"),
    ("S-0046", "F11", "ЯМЗ-236М2"),
    ("S-0079", "F13", "ЯМЗ-536"),
    ("S-0087", "F12", "ЯМЗ-536"),
    ("S-0132", "F08", "ЗМЗ-5234.10"),
    ("S-0144", "F09", "ЗМЗ-5234.10"),
    ("S-0163", "F09", "ЗМЗ-40905.10"),
}


def anomalies() -> list[tuple[str, str, str]]:
    data = json.loads((ROOT / "data" / "vehicles.json").read_text(encoding="utf-8"))
    return [
        (s["session_id"], s["anomaly_type"], v["engine_model"])
        for v in data["vehicles"]
        for s in v["sessions"]
        if s["status"] == "anomaly" and s["anomaly_type"]
    ]


@needs_matrix
def test_all_70_cells_have_status() -> None:
    assert len(CODES) == 14 and len(ENGINES) == 5
    assert {(c.code, c.engine) for c in CELLS} == {(c, e) for c in CODES for e in ENGINES}
    assert len(CELLS) == 70
    assert all(c.status in ("confirmed", "not_applicable", "silent", "unknown") for c in CELLS)


@needs_matrix
def test_every_reference_is_this_engine_and_existing_page() -> None:
    """Без текста страниц: документ — руководство этого двигателя, страница в 1..число страниц PDF."""
    for c in CELLS:
        checked, problems = verify_cell(c)
        assert problems == [], (c.code, c.engine, problems)
        assert checked.status == c.status


@needs_matrix
def test_conclusions_have_evidence() -> None:
    for c in CELLS:
        if c.applicable in ("true", "false"):
            assert c.basis is not None and c.basis.quote, (c.code, c.engine)
        if c.status == "not_applicable":
            assert c.why and not c.pages and not c.operations, (c.code, c.engine)
        if c.status == "confirmed":
            assert c.pages and c.operations, (c.code, c.engine)
            assert all(r.what for r in c.pages)
        if c.status == "unknown":
            assert not c.operations and not c.spare_parts, (c.code, c.engine)


@needs_matrix
def test_matrix_follows_source_decisions() -> None:
    """Сборка не меняет ручных решений о применимости (кроме понижения до unknown — его быть не должно)."""
    decided = {
        (code, engine): spec["cells"][group]["applicable"]
        for code, spec in SRC["codes"].items()
        for group, engines in SRC["groups"].items()
        for engine in engines
    }
    assert {(c.code, c.engine): c.applicable for c in CELLS} == decided


def test_exactly_seven_impossible_checks_in_data() -> None:
    found = {(sid, code, eng) for sid, code, eng in anomalies() if not is_compatible(code, eng)}
    assert found == IMPOSSIBLE
    for _, code, eng in IMPOSSIBLE:
        compat = check(code, eng)
        assert compat.why and compat.source  # механику — почему и где в руководстве


@needs_matrix
def test_compatible_anomalies_link_only_to_own_engine_manuals() -> None:
    by = {(c.code, c.engine): c for c in CELLS}
    for _, code, eng in anomalies():
        cell = by[(code, eng)]
        if cell.applicable == "false":
            continue
        own = {d.doc_id for d in documents_for_engine(eng)}
        assert {r.doc for r in cell.refs()} <= own, (code, eng)


def test_draft_rule_corrections_by_manuals() -> None:
    """Черновая таблица ошибалась: у ЗМЗ-5234 есть рециркуляция ОГ и нет цепи ГРМ."""
    assert is_compatible("F11", "ЗМЗ-5234.10")
    assert not is_compatible("F14", "ЗМЗ-5234.10")
    assert is_compatible("F14", "ЗМЗ-40904.10")


# ---------- проверка ячейки ----------

PAGE = "Регулировка зазоров. Зазор на холодном двигателе должен быть 0,20…0,30 мм. Заменить прокладку крышки."


def _page_text(doc: str, page: int) -> str | None:
    return PAGE if (doc, page) == ("zmz-5234-rk", 20) else None


def _cell(**kw: object) -> Cell:
    base: dict[str, object] = {
        "code": "F01",
        "engine": "ЗМЗ-5234.10",
        "applicable": "true",
        "basis": Ref("zmz-5234-rk", 20, "Регулировка зазоров."),
        "pages": [Ref("zmz-5234-rk", 20, "зазор на  холодном двигателе", "регулировка")],
        "operations": [Ref("zmz-5234-rk", 20, "Заменить прокладку крышки.")],
    }
    base.update(kw)
    return Cell(**base)  # type: ignore[arg-type]


def test_verify_keeps_valid_cell() -> None:
    cell, problems = verify_cell(_cell(), _page_text)
    assert problems == [] and cell.status == "confirmed"


def test_verify_drops_foreign_manual_and_missing_quote() -> None:
    cell, problems = verify_cell(
        _cell(
            operations=[
                Ref("yamz-236-re", 31, "Заменить прокладку крышки."),  # руководство другого двигателя
                Ref("zmz-5234-rk", 20, "Заменить головку цилиндров."),  # такой фразы на странице нет
                Ref("zmz-5234-rk", 999, "Заменить прокладку крышки."),  # страницы нет
            ]
        ),
        _page_text,
    )
    assert cell.operations == [] and cell.status == "silent"
    assert len(problems) == 3
    assert any("другого двигателя" in p for p in problems)


def test_verify_bad_basis_makes_cell_unknown() -> None:
    bad = Ref("zmz-5234-rk", 20, "нет такой цитаты")
    cell, problems = verify_cell(_cell(applicable="false", basis=bad), _page_text)
    assert cell.applicable == "unknown" and cell.status == "unknown"
    assert any("основание" in p for p in problems)


def test_normalize_ignores_layout() -> None:
    assert normalize("Зазор |  0,20…0,30\nмм") == normalize("зазор 0,20…0,30 мм")


# ---------- на собранном индексе: цитаты действительно на страницах ----------

INDEX = Path(os.environ.get("INDEX_DIR", ".index"))


@needs_matrix
@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_every_quote_is_on_its_page() -> None:
    from service.manuals.index import load_fragments

    pages: dict[tuple[str, int], list[str]] = defaultdict(list)
    for f in load_fragments(INDEX / "fragments.jsonl"):
        pages[(f.doc_id, f.page)].append(f.text)

    def page_text(doc: str, page: int) -> str | None:
        texts = pages.get((doc, page))
        return "\n".join(texts) if texts else None

    for c in CELLS:
        checked, problems = verify_cell(c, page_text)
        assert problems == [], (c.code, c.engine, problems)
        assert checked.status == c.status


@needs_matrix
def test_card_explanation_has_pages_for_confirmed_cell() -> None:
    from service.fault_matrix import _load, card_explanation

    cell = next(c for c in _load().values() if c.status == "confirmed" and c.pages)
    exp = card_explanation(cell.code, cell.engine)
    assert exp is not None and exp["pages"]
    assert {p["pdf_page"] for p in exp["pages"]} == {r.page for r in cell.pages}


# ---------- где лежит матрица (#96, шаг 2): в INDEX_DIR рядом с индексом, иначе data/ ----------


def test_impossible_checks_hold_without_matrix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Правило 5 не зависит от того, опубликована ли матрица: без неё «узла нет» — из источника матрицы (в git)."""
    monkeypatch.setattr(fault_matrix, "DATA_MATRIX_PATH", tmp_path / "нет.json")
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "index"))
    assert not matrix_loaded()
    found = {(sid, code, eng) for sid, code, eng in anomalies() if not is_compatible(code, eng)}
    assert found == IMPOSSIBLE
    for _, code, eng in IMPOSSIBLE:
        assert check(code, eng).why and check(code, eng).source
    assert fault_matrix.cell_for("F01", "ЯМЗ-236М2") is None  # работ и страниц без матрицы нет — не выдумываем
    assert fault_matrix.card_explanation("F01", "ЯМЗ-236М2") is None
    assert fault_matrix.matrix_status() == {"present": False}


def test_matrix_from_index_dir_wins_over_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    index = tmp_path / "index"
    monkeypatch.setenv("INDEX_DIR", str(index))
    monkeypatch.setattr(fault_matrix, "DATA_MATRIX_PATH", write_synthetic(tmp_path / "data" / "fault_matrix.json"))
    assert matrix_path() == tmp_path / "data" / "fault_matrix.json"
    assert fault_matrix.matrix_status()["source"] == "data"
    write_synthetic(index / "fault_matrix.json")
    assert matrix_path() == index / "fault_matrix.json"
    assert fault_matrix.matrix_status() == {"present": True, "source": "index", "cells": 2, "confirmed": 1}


def test_synthetic_matrix_drives_card_and_compat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setattr(fault_matrix, "DATA_MATRIX_PATH", write_synthetic(tmp_path / "fault_matrix.json"))
    exp = fault_matrix.card_explanation("F01", "ЯМЗ-236М2")
    assert exp is not None and exp["status"] == "confirmed"
    assert [s["pdf_page"] for s in exp["steps"]] == [11] and exp["steps"][0]["tools"] == ["ключ"]
    assert exp["parts"][0]["designation"] == "000-0000000"
    assert not is_compatible("F09", "ЗМЗ-5234.10") and check("F09", "ЗМЗ-5234.10").source == "zmz-5234-rk, стр. 3"
    assert is_compatible("F02", "ЯМЗ-236М2")  # ячейки нет в матрице — заявку не блокирует, как и раньше


def test_save_matrix_writes_data_and_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Сборка пишет матрицу и в data/, и в INDEX_DIR — оттуда её выкладывает kb_store.publish_index."""
    data = tmp_path / "data" / "fault_matrix.json"
    data.parent.mkdir()
    monkeypatch.setattr(fault_matrix, "DATA_MATRIX_PATH", data)
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "нет-индекса"))
    assert fault_matrix.save_matrix({"cells": []}) == [data]
    (tmp_path / "index").mkdir()
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "index"))
    assert fault_matrix.save_matrix({"cells": []}) == [data, tmp_path / "index" / "fault_matrix.json"]
    assert (tmp_path / "index" / "fault_matrix.json").read_text(encoding="utf-8") == data.read_text(encoding="utf-8")
