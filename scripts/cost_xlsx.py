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

from cost_layers import LOCAL_VOICE, PILOT_PER_DAY, monthly_fixed, other, pilot, voice_option
from service.store import llm_price_native, price_table

ROOT = Path(__file__).resolve().parents[1]
COST_DIR = ROOT / "reports" / "cost"
DEFAULT_TEMPLATE = "~/hackathon-blind-pack/04_shablon_rascheta.xlsx"
SHEET = "Расчёт"
STEP_ROWS = (9, 10, 11, 12)
COMMENT_CELLS = ("A17", "A18", "A19")
SCENARIO = "С1"

# Шаги агента С1 для шаблона. Каждый вызов модели попадает ровно в одну строку (итог шаблона = замер):
ANSWER = "Ответ механику: план поиска + ответ (диагноз и поиск — кодом; доп. круги модели — сюда же)"
DRAFT = "Заявка: модель готовит черновик (draft_ticket)"
FINAL = "Заявка: итог механику перед подтверждением (все ходы после черновика)"


def step_name(question: int, step: int) -> str:
    if question == 1:
        return ANSWER
    return DRAFT if step == 1 else FINAL


EMB_NAME = "Поиск по руководству: эмбеддинг запроса"


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
    emb: list[dict[str, str]] = []
    with (COST_DIR / f"{run['label']}.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["scenario"] == SCENARIO and row["kind"] == "эмбеддинг":
                emb.append(row)
            if row["scenario"] != SCENARIO or row["kind"] != "модель":
                continue
            groups[step_name(int(row["question"]), int(row["step"]))].append(row)
    repeat = int(run.get("repeat", 1))
    out: list[dict[str, Any]] = []
    for name in (ANSWER, DRAFT, FINAL):
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
    limit = len(STEP_ROWS) - (1 if emb else 0)
    out = out[:limit]
    if emb:  # поиск по смыслу — тоже вызов модели (эмбеддинги Yandex), строкой в рублях
        out.append(
            {
                "name": EMB_NAME,
                "calls": round(len(emb) / repeat, 2),
                "tokens_in": round(sum(int(r["tokens_in"]) for r in emb) / len(emb)),
                "tokens_cached": 0,
                "tokens_out": 0,
                "model": "Yandex text-search-query",
                "embedding": True,
            }
        )
    return out


def effective_in_price(step: dict[str, Any], price: dict[str, float]) -> float:
    total = step["tokens_in"] or 1
    cached = min(step["tokens_cached"], total)
    return float((cached * price["in_cached"] + (total - cached) * price["in"]) / total)


def model_rub(steps: list[dict[str, Any]], price: dict[str, float], currency: str, rate: float) -> float:
    """То же, что формула шаблона в I9:I12 и I13 — для проверки и отчёта."""
    k = rate if currency == "USD" else 1.0
    total = 0.0
    for s in steps:
        if s.get("embedding"):
            total += s["calls"] * s["tokens_in"] * other("embedding") / 1000
        else:
            per_call = s["tokens_in"] * effective_in_price(s, price) + s["tokens_out"] * price["out"]
            total += s["calls"] * per_call / 1e6 * k
    return total


def comment(run: dict[str, Any], price_note: str) -> list[str]:
    """Три строки: запрос и допущения; голос — опция; постоянные в месяц на парк."""
    t = price_table()
    rest = ", ".join(f"{k} {v['rub']}" for k, v in run["scenarios"].items() if k != SCENARIO)
    fixed = monthly_fixed(run)
    voice = voice_option(run)
    voice_txt = f"+{voice} ₽ на вопрос" if voice is not None else "в замере нет"
    return [
        f"Запрос = сценарий видео С1 (вопрос + черновик заявки): модель + эмбеддинг запроса, токены — среднее "
        f"{run['repeat']} прогонов на демо (make cost, замер {run['label']}); вход — со скидкой за кэш по замеренной "
        f"доле. {price_note} Другие сценарии, ₽: {rest}. Цены — официальные, курс ЦБ {t['usd_rub']['value']} на "
        f"{t['usd_rub']['date']}, без НДС.",
        f"Голос — опция, не в итоге: распознавание 15 с + синтез ответа (SpeechKit) — {voice_txt}; {LOCAL_VOICE}.",
        f"Постоянные в месяц на парк, не в запрос: контейнер {fixed['container_rub']} ₽ в бесплатном уровне "
        f"({fixed['container_rub_no_free_tier']} ₽ без него) при {fixed['questions']} вопросах; хранилище индекса и "
        f"PDF {fixed['storage_gb']} ГБ — {fixed['storage_rub']} ₽ ({fixed['storage_rub_no_free_tier']} ₽ без "
        "бесплатного объёма). Пилот без бесплатного уровня, парк 50 машин: "
        + "; ".join(
            f"{p['per_day']} запросов в день — площадка {p['platform_rub']} ₽/мес, {p['platform_per_vehicle_rub']} ₽ "
            "на машину"
            for p in (pilot(run, n) for n in PILOT_PER_DAY)
        )
        + " (подробно — reports/cost.md).",
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
        if s.get("embedding"):  # ₽ без НДС за 1 млн токенов (на странице — за 1000)
            ws[f"F{row}"], ws[f"G{row}"], ws[f"H{row}"] = round(other("embedding") * 1000, 4), 0, "₽"
            continue
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
