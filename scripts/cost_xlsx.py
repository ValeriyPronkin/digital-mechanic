"""Шаблон организаторов «калькулятор экономики решения» по замеру `make cost` (issue #16, ответ в #19).

  make cost-xlsx                     # последний замер DeepSeek → reports/cost-template-<замер>.xlsx
  make cost-xlsx XLSX_LABEL=gigachat-1    # конкретный замер (модель и валюта — из него)

Шаблон — COST_TEMPLATE (по умолчанию ~/hackathon-blind-pack/04_shablon_rascheta.xlsx, в git не входит).
Заполняются только жёлтые ячейки листа «Расчёт»: I3 — курс ЦБ, A9:H12 — шаги агента с вызовом модели для одного
запроса (сценарий видео С1: вопрос механика + черновик заявки), A17:A19 — комментарий. Формулы шаблона не трогаем.
Цена входа — эффективная: доля токенов из кэша провайдера по замеру × цена кэша + остальное × цена входа.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import openpyxl

from service.store import llm_price_native, price_table

ROOT = Path(__file__).resolve().parents[1]
COST_DIR = ROOT / "reports" / "cost"
DEFAULT_TEMPLATE = "~/hackathon-blind-pack/04_shablon_rascheta.xlsx"
SHEET = "Расчёт"
STEP_ROWS = (9, 10, 11, 12)
COMMENT_CELLS = ("A17", "A18", "A19")
SCENARIO = "С1"

# (вопрос, шаг модели) в С1 → название шага агента для шаблона
STEP_NAMES = {
    (1, 1): "Ответ механику: что с двигателем и что делать (диагноз и поиск — кодом)",
    (2, 1): "Заявка: модель готовит черновик (draft_ticket)",
    (2, 2): "Заявка: итог механику перед подтверждением",
}
EXTRA = "Дополнительный круг: модель сама ищет по руководству"


def pick_run(label: str | None) -> dict[str, Any]:
    runs: list[dict[str, Any]] = sorted(
        (json.loads(p.read_text(encoding="utf-8")) for p in COST_DIR.glob("*.json")), key=lambda d: d["at"]
    )
    if label:
        found = [r for r in runs if r["label"] == label]
        if not found:
            raise SystemExit(f"нет замера {label} в {COST_DIR}")
        return found[0]
    deepseek = [r for r in runs if r.get("provider") == "deepseek"]
    if not deepseek:
        raise SystemExit("нет замера DeepSeek с провайдером в итогах — сначала make cost")
    return deepseek[-1]


def step_rows(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Шаги С1 с вызовом модели: вызовов на запрос, средние токены вход/из кэша/выход на вызов."""
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    with (COST_DIR / f"{run['label']}.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["scenario"] != SCENARIO or row["kind"] != "модель":
                continue
            key = (int(row["question"]), int(row["step"]))
            groups[STEP_NAMES.get(key, EXTRA)].append(row)
    repeat = int(run.get("repeat", 1))
    out: list[dict[str, Any]] = []
    for name in [*STEP_NAMES.values(), EXTRA]:
        rows = groups.get(name)
        if not rows:
            continue
        n = len(rows)
        out.append(
            {
                "name": name,
                "calls": round(n / repeat, 2),
                "tokens_in": round(sum(int(r["tokens_in"]) for r in rows) / n),
                "tokens_cached": round(sum(int(r["tokens_cached"]) for r in rows) / n),
                "tokens_out": round(sum(int(r["tokens_out"]) for r in rows) / n),
                "model": max({r["name"] for r in rows}, key=[r["name"] for r in rows].count),  # как ответил API
            }
        )
    return out[: len(STEP_ROWS)]


def effective_in_price(step: dict[str, Any], price: dict[str, float]) -> float:
    total = step["tokens_in"] or 1
    cached = min(step["tokens_cached"], total)
    return float((cached * price["in_cached"] + (total - cached) * price["in"]) / total)


def model_rub(steps: list[dict[str, Any]], price: dict[str, float], currency: str, rate: float) -> float:
    """То же, что формула шаблона в I9:I12 и I13 — для проверки и отчёта."""
    k = rate if currency == "USD" else 1.0
    return float(
        sum(
            s["calls"] * (s["tokens_in"] * effective_in_price(s, price) + s["tokens_out"] * price["out"]) / 1e6 * k
            for s in steps
        )
    )


def comment(run: dict[str, Any], price_note: str) -> list[str]:
    t = price_table()
    o = t["other"]
    scen = run["scenarios"]
    rest = ", ".join(f"{k} {v['rub']}" for k, v in scen.items() if k != SCENARIO)
    return [
        f"Запрос = сценарий видео С1 (вопрос + черновик заявки), токены — среднее {run['repeat']} прогонов на демо "
        f"(make cost, замер {run['label']}); вход — с учётом скидки за кэш по замеренной доле. {price_note} "
        f"Другие сценарии, ₽: {rest}.",
        "Без модели: карточка проверки и пояснение по руководству — код, 0 ₽; поиск по смыслу ≈0,0002 ₽ на запрос "
        f"(эмбеддинг {o['embedding']['value']} ₽/1000 ток. с НДС); голос (не в этой таблице): распознавание "
        f"{o['stt_sync']['value']} ₽/15 с и синтез {o['tts_v1']['value']} ₽/1 млн символов (API v1) с НДС.",
        f"Инфраструктура: Serverless Containers {o['container_vcpu_hour']['value']} ₽/vCPU·ч и "
        f"{o['container_ram_gb_hour']['value']} ₽/ГБ·ч с НДС сверх бесплатного уровня; хранилище "
        f"{o['object_storage_gb_month']['value']} ₽/ГБ·мес с НДС (индекс и PDF ~0,2 ГБ). Цены — официальные "
        f"страницы, курс ЦБ {t['usd_rub']['value']} ₽/$ на {t['usd_rub']['date']}; суммы без НДС.",
    ]


def fill(template: Path, out: Path, run: dict[str, Any]) -> dict[str, Any]:
    provider = run.get("provider") or "deepseek"
    price, currency = llm_price_native(provider)
    rate = float(price_table()["usd_rub"]["value"])
    steps = step_rows(run)
    if not steps:
        raise SystemExit(f"в замере {run['label']} нет шагов модели сценария {SCENARIO}")
    llm = price_table()["llm"][provider]
    note = str(llm.get("note", ""))
    price_note = f"Тариф: {note}." if note else ""

    wb = openpyxl.load_workbook(template)
    ws = wb[SHEET]
    ws["I3"] = rate
    for row, s in zip(STEP_ROWS, steps, strict=False):
        ws[f"A{row}"] = s["name"]
        ws[f"B{row}"] = s["model"]
        ws[f"C{row}"] = s["calls"]
        ws[f"D{row}"] = s["tokens_in"]
        ws[f"E{row}"] = s["tokens_out"]
        ws[f"F{row}"] = round(effective_in_price(s, price), 6)
        ws[f"G{row}"] = round(price["out"], 6)
        ws[f"H{row}"] = "$" if currency == "USD" else "₽"
    for cell, text in zip(COMMENT_CELLS, comment(run, price_note), strict=True):
        ws[cell] = text
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return {"rub": model_rub(steps, price, currency, rate), "steps": steps}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", help="замер из reports/cost/ (по умолчанию — последний DeepSeek)")
    ap.add_argument("--template", default=os.environ.get("COST_TEMPLATE", DEFAULT_TEMPLATE))
    args = ap.parse_args()
    template = Path(args.template).expanduser()
    if not template.is_file():
        raise SystemExit(f"нет шаблона {template} (COST_TEMPLATE)")
    run = pick_run(args.label)
    out = ROOT / "reports" / f"cost-template-{run['label']}.xlsx"
    res = fill(template, out, run)
    for s in res["steps"]:
        toks = f"{s['tokens_in']} ({s['tokens_cached']} из кэша) / {s['tokens_out']}"
        print(f"  {s['name']}: {s['calls']} вызова, {toks}")
    print(f"{out.relative_to(ROOT)}: модель на 1 запрос ≈ {res['rub']:.4f} ₽ без НДС")
    return 0


if __name__ == "__main__":
    sys.exit(main())
