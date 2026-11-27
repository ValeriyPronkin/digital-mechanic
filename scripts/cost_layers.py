"""Слои себестоимости (issue #16, указание штурмана 26.11; ответ организаторов в чате 26.11):

1. Запрос — модель + эмбеддинг запроса (по замеру `make cost`); только он идёт в шаблон организаторов.
2. Разово — индексация руководств: OCR страниц без текста + эмбеддинги всех фрагментов (`one_time_index`).
3. Голос — опция к запросу: распознавание вопроса и синтез ответа (SpeechKit) или локально на своём сервере.
4. Парк в месяц — запросы × цена запроса по примеру организаторов (`fleet_month`) + контейнер стенда и хранилище.

Ответ организаторов (26.11): «Эмбеддинги запроса тоже входят. Разовую индексацию руководств посчитайте отдельной
строкой. Кроме стоимости одного сценария, покажите разбивку по шагам и пересчёт на парк. Пример допущения для
пересчёта: 50 машин, проверка раз в две недели, два-три вопроса механика на проверку. Допущения назовите явно.»

Тарифы — `data/prices.json` (официальные страницы, без НДС). Допущения — в `ASSUMPTIONS` и `INDEX`, их видно в отчёте.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from service.store import ex_vat, price_table

ROOT = Path(__file__).resolve().parents[1]

ASSUMPTIONS: dict[str, float] = {
    "vehicles": 50,  # пример организаторов (26.11); в data/vehicles.json тоже 50
    "checks_per_vehicle_month": 26 / 12,  # «проверка раз в две недели»: 26 в год
    "questions_per_check": 3,  # «два-три вопроса механика на проверку» — верхняя граница
    "questions_per_check_low": 2,  # нижняя граница
    "http_calls_per_question": 10,  # вызовов контейнера на вопрос: страница, API, чат
    "overhead_s": 0.5,  # обработка запроса вне модели, с
    "vcpu": 1,  # ресурсы контейнера стенда
    "ram_gb": 1,
}
# Индекс руководств, который читает стенд (`/health` → manuals_index.fragments, reports/2026-11-26-s3-stand-index.md).
INDEX: dict[str, float] = {
    "pages": 1743,  # 6 PDF (STATUS «Метрики», паспорт индекса)
    "ocr_pages": 41,  # страниц меньше 50 знаков текста → Yandex OCR (pdf.LOW_TEXT_CHARS; low_text_pages паспорта)
    "fragments": 3593,  # фрагментов в индексе стенда — каждый один раз через text-search-doc
    # Средняя длина текста, который уходит в эмбеддинг (`section + "\n" + text`, до EMB_MAX_CHARS): 630 знаков —
    # замер сборки `python -m service.manuals build --no-yandex` (3 545 фрагментов без OCR, 2 234 818 знаков).
    "chars_per_fragment": 630,
    # Знаков на токен эмбеддинга: 3 — допущение кода (manuals/yandex.py, EMB_MAX_CHARS и оценка query_tokens);
    # numTokens по фрагментам лежит только в кэше индекса в бакете, локально его нет — поэтому диапазон.
    "chars_per_token": 3.0,
    "chars_per_token_low": 2.5,  # больше токенов — дороже
    "chars_per_token_high": 4.0,
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


STORAGE_GB_MEASURED = 0.178  # индекс + 6 PDF на диске, замер 26.11 (reports/cost.md, слой «Постоянные»)


def storage_gb() -> float:
    """Что лежит в бакете: индекс без кэша извлечения + PDF руководств. Без PDF на диске — замер 26.11:
    иначе итог зависит от того, что лежит на машине, где запускали скрипт (было 0,032 ГБ в шаблоне)."""
    index = _dir_gb(Path(os.environ.get("INDEX_DIR", ROOT / ".index")), skip=("extract",))
    pdf = _dir_gb(Path(os.environ.get("MANUALS_DIR", ROOT / "manuals")).expanduser())
    return round(index + pdf, 3) if pdf else STORAGE_GB_MEASURED


def question_seconds(run: dict[str, Any]) -> float:
    """Среднее время модели на вопрос по замеру + обработка вне модели."""
    ms = [sc.get("llm_ms", 0) for sc in run["scenarios"].values() if sc.get("llm_ms")]
    return (sum(ms) / len(ms) / 1000 if ms else 3.0) + ASSUMPTIONS["overhead_s"]


def monthly_fixed(run: dict[str, Any]) -> dict[str, Any]:
    """Постоянные в месяц на парк, ₽ без НДС: с бесплатным уровнем Yandex Cloud и без него."""
    a = ASSUMPTIONS
    questions = round(a["vehicles"] * a["checks_per_vehicle_month"] * a["questions_per_check"])
    hours = questions * question_seconds(run) / 3600
    vcpu_h, ram_gbh = hours * a["vcpu"], hours * a["ram_gb"]
    calls = questions * a["http_calls_per_question"]
    gb = storage_gb()
    p_cpu, p_ram = other("container_vcpu_hour"), other("container_ram_gb_hour")
    p_inv, p_gb = other("container_invocations_million"), other("object_storage_gb_month")
    container_full = vcpu_h * p_cpu + ram_gbh * p_ram + calls / 1e6 * p_inv
    container_free = max(0, vcpu_h - 5) * p_cpu + max(0, ram_gbh - 10) * p_ram + max(0, calls - 1e6) / 1e6 * p_inv
    return {
        "questions": questions,
        "hours": round(hours, 3),
        "storage_gb": gb,
        "container_rub": round(container_free, 2),
        "container_rub_no_free_tier": round(container_full, 2),
        "storage_rub": round(max(0.0, gb - 1) * p_gb, 2),
        "storage_rub_no_free_tier": round(gb * p_gb, 2),
    }


def voice_option(run: dict[str, Any] | None = None) -> float:
    """Голос к одному вопросу, ₽ без НДС, по тарифу и правилам кода (src/service/voice.py): распознавание —
    один блок 15 с (вопрос до 15 с); синтез — короткая фраза `speech_for` до 250 знаков по более дешёвому API.
    Это верхняя граница; живой замер 26.11 — 0,27 ₽ (reports/2026-11-26-voice-cost.md), повтор фразы — синтез 0 ₽.
    `rub_voice` в замерах до voice-cost считал синтез всего ответа по API v1 (1,19 ₽) и здесь не используется."""
    from service.voice import stt_cost_rub, tts_cost_rub

    return round(stt_cost_rub(15) + tts_cost_rub(250), 4)


def one_time_index() -> dict[str, Any]:
    """Разовая индексация руководств, ₽ без НДС: OCR страниц без текста + эмбеддинги всех фрагментов.
    Повторная сборка берёт OCR и эмбеддинги из кэша (`.index/cache`) и не платит."""
    i = INDEX
    chars = i["fragments"] * i["chars_per_fragment"]
    p_ocr, p_emb = other("ocr_page"), other("embedding")

    def emb_rub(chars_per_token: float) -> float:
        return chars / chars_per_token * p_emb / 1000

    ocr = i["ocr_pages"] * p_ocr
    emb = emb_rub(i["chars_per_token"])
    return {
        "ocr_pages": int(i["ocr_pages"]),
        "ocr_rub": round(ocr, 2),
        "fragments": int(i["fragments"]),
        "emb_tokens": round(chars / i["chars_per_token"]),
        "emb_rub": round(emb, 2),
        "emb_rub_range": (round(emb_rub(i["chars_per_token_high"]), 2), round(emb_rub(i["chars_per_token_low"]), 2)),
        "rub": round(ocr + emb, 2),
        "rub_range": (
            round(ocr + emb_rub(i["chars_per_token_high"]), 2),
            round(ocr + emb_rub(i["chars_per_token_low"]), 2),
        ),
    }


def fleet_month(run: dict[str, Any], first: str = "С1", more: str = "Р1") -> dict[str, Any]:
    """Парк в месяц, ₽ без НДС, по примеру организаторов. Проверка = сценарий `first` (вопрос + заявка, с
    эмбеддингом запроса) + ещё 1–2 вопроса по цене `more` (вопрос по руководству). Оценка сверху: каждая проверка
    считается отклонением с заявкой, хотя «норма» и «сбой записи» дешевле (Нр, С3)."""
    a = ASSUMPTIONS
    checks = a["vehicles"] * a["checks_per_vehicle_month"]
    c1, extra = float(run["scenarios"][first]["rub"]), float(run["scenarios"][more]["rub"])

    def per_check(q: float) -> float:
        return c1 + (q - 1) * extra

    lo, hi = per_check(a["questions_per_check_low"]), per_check(a["questions_per_check"])
    fixed = monthly_fixed(run)
    voice = voice_option(run)
    return {
        "checks": round(checks, 1),
        "per_check_rub": (round(lo, 4), round(hi, 4)),
        "requests_rub": (round(checks * lo, 2), round(checks * hi, 2)),
        "fixed_rub": round(fixed["container_rub"] + fixed["storage_rub"], 2),
        "fixed_rub_no_free_tier": round(fixed["container_rub_no_free_tier"] + fixed["storage_rub_no_free_tier"], 2),
        "total_rub": (
            round(checks * lo + fixed["container_rub"] + fixed["storage_rub"], 2),
            round(checks * hi + fixed["container_rub"] + fixed["storage_rub"], 2),
        ),
        "voice_rub": round(checks * a["questions_per_check"] * voice, 2),  # если каждый вопрос голосом
        "questions": fixed["questions"],
    }
