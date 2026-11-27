"""make cost-xlsx: жёлтые ячейки шаблона заполнены по замеру, формулы шаблона не тронуты (issue #16, #19)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import openpyxl
import pytest

import cost_xlsx
from service.store import llm_price_native, price_table

FORMULA = (
    '=IF(C{r}="","",IF(AND(H{r}="$",$I$3=""),"впишите курс $",C{r}*(D{r}*F{r}+E{r}*G{r})/1000000*IF(H{r}="$",$I$3,1)))'
)


def _template(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Расчёт"
    for r in range(8, 13):
        ws[f"I{r}"] = FORMULA.format(r=r)
    ws["I13"] = "=SUM(I9:I12)"
    wb.save(path)


def _run(cost_dir: Path) -> dict:
    run = {"label": "t1", "at": "2026-11-26 16:00", "repeat": 2, "provider": "deepseek", "model": "deepseek-chat",
           "scenarios": {"С1": {"rub": 0.07}, "С3": {"rub": 0.01}, "Р1": {"rub": 0.05}}}  # fmt: skip
    rows = []
    for _ in range(2):
        rows += [
            {"scenario": "С1", "question": 1, "step": 1, "kind": "модель", "name": "deepseek-flash",
             "tokens_in": 2800, "tokens_cached": 2600, "tokens_out": 300},
            {"scenario": "С1", "question": 1, "step": 0, "kind": "инструмент", "name": "search_manual (код)",
             "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0},
            {"scenario": "С1", "question": 2, "step": 1, "kind": "модель", "name": "deepseek-flash",
             "tokens_in": 3100, "tokens_cached": 2900, "tokens_out": 80},
            {"scenario": "С3", "question": 1, "step": 1, "kind": "модель", "name": "deepseek-flash",
             "tokens_in": 1700, "tokens_cached": 1500, "tokens_out": 70},
        ]  # fmt: skip
    (cost_dir / "t1.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    with (cost_dir / "t1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[*list(rows[0]), "rub", "ms"])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "rub": 0, "ms": 0})
    return run


def test_fill_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cost_xlsx, "COST_DIR", tmp_path)
    tpl, out = tmp_path / "tpl.xlsx", tmp_path / "out.xlsx"
    _template(tpl)
    run = _run(tmp_path)
    res = cost_xlsx.fill(tpl, out, cost_xlsx.pick_run("t1"))
    ws = openpyxl.load_workbook(out)["Расчёт"]
    assert ws["I3"].value == price_table()["usd_rub"]["value"]
    assert ws["B9"].value == "deepseek-flash"  # модель — как ответил API
    assert (ws["C9"].value, ws["D9"].value, ws["E9"].value, ws["H9"].value) == (1.0, 2800, 300, "$")
    assert ws["A10"].value.startswith("Заявка") and ws["A11"].value is None  # только шаги С1, по факту
    price, _ = llm_price_native("deepseek")
    assert price["in_cached"] < ws["F9"].value < price["in"]  # вход — с учётом доли кэша
    for r in range(9, 13):
        assert ws[f"I{r}"].value == FORMULA.format(r=r)  # формулы шаблона не тронуты
    assert ws["I13"].value == "=SUM(I9:I12)"
    assert all(ws[c].value for c in ("A17", "A18", "A19"))
    # то, что посчитает Excel по формуле шаблона
    rate = ws["I3"].value
    excel = sum(ws[f"C{r}"].value * (ws[f"D{r}"].value * ws[f"F{r}"].value + ws[f"E{r}"].value * ws[f"G{r}"].value)
                / 1e6 * rate for r in (9, 10))  # fmt: skip
    assert res["rub"] == pytest.approx(excel, rel=1e-4)
    assert run["label"] == "t1"


def test_embedding_row_and_layered_comment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаблон — только запрос (модель + эмбеддинг); голос и постоянные в месяц — в комментарии, не в итоге."""
    monkeypatch.setattr(cost_xlsx, "COST_DIR", tmp_path)
    tpl, out = tmp_path / "tpl.xlsx", tmp_path / "out.xlsx"
    _template(tpl)
    run = _run(tmp_path)
    run["scenarios"]["Г1"] = {"rub": 0.04, "rub_voice": 0.67, "llm_ms": 2000}
    (tmp_path / "t1.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    with (tmp_path / "t1.csv").open("a", newline="", encoding="utf-8") as f:
        for _ in range(2):
            f.write("С1,1,0,эмбеддинг,text-search-query,12,0,0,0.0001,0\n")
    cost_xlsx.fill(tpl, out, cost_xlsx.pick_run("t1"))
    ws = openpyxl.load_workbook(out)["Расчёт"]
    emb_row = next(r for r in range(9, 13) if ws[f"A{r}"].value == cost_xlsx.EMB_NAME)
    assert (ws[f"C{emb_row}"].value, ws[f"D{emb_row}"].value, ws[f"E{emb_row}"].value) == (1.0, 12, 0)
    assert ws[f"H{emb_row}"].value == "₽" and ws[f"F{emb_row}"].value == pytest.approx(0.0101 / 1.22 * 1000, rel=1e-3)
    # ответ организаторов 26.11: разовая индексация отдельной строкой, пересчёт на парк, голос — опция
    assert "индексация руководств" in ws["A18"].value and "OCR 41 стр." in ws["A18"].value
    assert "Голос — опция" in ws["A18"].value and "0.2666" in ws["A18"].value and "локально" in ws["A18"].value
    assert "Парк в месяц" in ws["A19"].value and "50 машин" in ws["A19"].value
    assert all(len(ws[c].value) <= 500 for c in ("A17", "A18", "A19"))  # «до 3 строк» в ячейке A:J


def test_refill_clears_rows_of_previous_fill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаблон по умолчанию — сам сдаваемый файл: строки прошлого заполнения, которых нет в замере, очищаются."""
    monkeypatch.setattr(cost_xlsx, "COST_DIR", tmp_path)
    tpl = tmp_path / "tpl.xlsx"
    _template(tpl)
    wb = openpyxl.load_workbook(tpl)
    for col, val in zip("ABCDEFGH", ("старый шаг", "m", 1, 100, 10, 0.1, 0.2, "$"), strict=True):
        wb["Расчёт"][f"{col}12"] = val
    wb.save(tpl)
    _run(tmp_path)
    cost_xlsx.fill(tpl, tpl, cost_xlsx.pick_run("t1"))  # тот же файл — и шаблон, и результат
    ws = openpyxl.load_workbook(tpl)["Расчёт"]
    assert all(ws[f"{c}12"].value is None for c in "ABCDEFGH")
    assert ws["I12"].value == FORMULA.format(r=12)
