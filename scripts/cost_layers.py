"""Слои себестоимости (issue #16, указание штурмана 26.11):

1. Запрос — модель + эмбеддинг запроса (по замеру `make cost`); только он идёт в шаблон организаторов.
2. Голос — опция к запросу: распознавание вопроса и синтез ответа (SpeechKit) или локально на своём сервере.
3. Постоянные в месяц на парк — контейнер стенда и хранилище; от числа запросов почти не зависят, в запрос не входят.

Тарифы — `data/prices.json` (официальные страницы, без НДС). Допущения — в `ASSUMPTIONS`, их видно в отчёте.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from service.store import ex_vat, price_table

ROOT = Path(__file__).resolve().parents[1]

ASSUMPTIONS: dict[str, float] = {
    "vehicles": 50,  # парк из data/vehicles.json
    "checks_per_vehicle_month": 4,  # проверок одной машины в месяц
    "questions_per_check": 2,  # вопросов механика к агенту на проверку
    "http_calls_per_question": 10,  # вызовов контейнера на вопрос: страница, API, чат
    "overhead_s": 0.5,  # обработка запроса вне модели, с
    "vcpu": 1,  # ресурсы контейнера стенда
    "ram_gb": 1,
}
LOCAL_VOICE = (
    "без облака: распознавание и синтез речи локально на своём сервере (открытые модели) — 0 ₽ за запрос, "
    "затраты — сервер клиента"
)


def other(name: str) -> float:
    row = price_table()["other"][name]
    return ex_vat(float(row["value"]), bool(row.get("vat_included")))


def _dir_gb(path: Path, skip: tuple[str, ...] = ()) -> float:
    if not path.exists():
        return 0.0
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not any(x in p.parts for x in skip))
    return total / 2**30


def storage_gb() -> float:
    """Что лежит в бакете: индекс без кэша извлечения + PDF руководств (по диску; нет на диске — 0,2 ГБ)."""
    index = _dir_gb(Path(os.environ.get("INDEX_DIR", ROOT / ".index")), skip=("extract",))
    pdf = _dir_gb(Path(os.environ.get("MANUALS_DIR", ROOT / "manuals")).expanduser())
    return round(index + pdf, 3) or 0.2


def question_seconds(run: dict[str, Any]) -> float:
    """Среднее время модели на вопрос по замеру + обработка вне модели."""
    ms = [sc.get("llm_ms", 0) for sc in run["scenarios"].values() if sc.get("llm_ms")]
    return (sum(ms) / len(ms) / 1000 if ms else 3.0) + ASSUMPTIONS["overhead_s"]


def monthly_fixed(run: dict[str, Any]) -> dict[str, Any]:
    """Постоянные в месяц на парк, ₽ без НДС: с бесплатным уровнем Yandex Cloud и без него."""
    a = ASSUMPTIONS
    questions = a["vehicles"] * a["checks_per_vehicle_month"] * a["questions_per_check"]
    hours = questions * question_seconds(run) / 3600
    vcpu_h, ram_gbh = hours * a["vcpu"], hours * a["ram_gb"]
    calls = questions * a["http_calls_per_question"]
    gb = storage_gb()
    p_cpu, p_ram = other("container_vcpu_hour"), other("container_ram_gb_hour")
    p_inv, p_gb = other("container_invocations_million"), other("object_storage_gb_month")
    container_full = vcpu_h * p_cpu + ram_gbh * p_ram + calls / 1e6 * p_inv
    container_free = max(0, vcpu_h - 5) * p_cpu + max(0, ram_gbh - 10) * p_ram + max(0, calls - 1e6) / 1e6 * p_inv
    return {
        "questions": int(questions),
        "hours": round(hours, 3),
        "storage_gb": gb,
        "container_rub": round(container_free, 2),
        "container_rub_no_free_tier": round(container_full, 2),
        "storage_rub": round(max(0.0, gb - 1) * p_gb, 2),
        "storage_rub_no_free_tier": round(gb * p_gb, 2),
    }


def voice_option(run: dict[str, Any]) -> float | None:
    """Голос к одному вопросу (Г1), ₽ без НДС; None — в замере нет голосового сценария."""
    sc = run["scenarios"].get("Г1")
    return sc.get("rub_voice") if sc else None
