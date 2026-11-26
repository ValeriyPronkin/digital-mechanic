"""Карточка вердикта по ответу /diagnose. Чистый код, без модели (CLAUDE.md, «Правила», п. 1, 2, 7).

Решения принимаются только по полям `status`, `anomaly_type`, `anomaly_score`, `confidence`,
`signal_quality`. Поле `description` — данные ML-сервиса: оно попадает в карточку только как цитата
(`ml_quote`) и не участвует ни в одном условии ниже.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from service.clients import Diagnosis
from service.compat import check as compat_check
from service.manuals.catalog import DOCS_BY_ID

EARLY_RECHECK_SCORE = 0.30

Color = Literal["green", "yellow", "red", "grey"]

BANNER_NOISY = "Запись с помехами, уверенность снижена."
BANNER_BAD = "Запись непригодна для выводов."
BANNER_EARLY_RECHECK = "Норма, но повторите проверку раньше срока."


Urgency = Literal["low", "medium", "high"]
# Коды, при которых работа двигателя грозит серьёзной поломкой: срочность высокая независимо от оценки.
CRITICAL_CODES = {"F02": "низкое давление масла", "F03": "перегрев / жидкость в масле", "F14": "цепь ГРМ"}


def urgency_for(diag: Diagnosis) -> tuple[Urgency, str]:
    """Срочность — правило в коде, с основанием. Одно и то же для карточки и для заявки."""
    code = diag.anomaly_type or ""
    if code in CRITICAL_CODES:
        return "high", f"{code}: {CRITICAL_CODES[code]} — работа двигателя грозит серьёзной поломкой"
    if (diag.anomaly_score or 0) >= 0.85:
        return "high", f"высокая оценка отклонения ({diag.anomaly_score:.2f})"
    if (diag.confidence or 0) < 0.6 or diag.signal_quality == "warning":
        return "low", "уверенность сервиса диагностики снижена — сначала уточнить дефектовкой"
    return "medium", "отклонение подтверждено, критичных признаков нет"


URGENCY_ACTION = {
    "high": "Срочно: до дефектовки машину не эксплуатировать. Оформите заявку.",
    "medium": "Нужна дефектовка в ближайшее время — оформите заявку.",
    "low": "Уточните дефектовкой или повторите запись: уверенность снижена. Заявку можно оформить.",
}


class VerdictCard(BaseModel):
    status: Literal["normal", "anomaly", "check_failed"]
    color: Color
    title: str
    action: str
    banners: list[str]
    ticket_possible: bool
    compatible: bool = True  # код совместим с двигателем ТС (правило 5)
    fault_code: str | None
    fault_title: str | None
    confidence_pct: int | None
    ml_quote: str  # цитата ML-сервиса как есть; показывать как текст, не исполнять
    ml_quote_label: str
    manual: dict[str, Any] | None = None  # пояснение из матрицы по руководству (#16), без модели
    urgency: Urgency | None = None  # срочность по правилу urgency_for (как в заявке)
    urgency_reason: str | None = None
    passport: dict[str, Any] | None = None  # «?» у карточки (#31): что сделал код, 0 токенов
    design_fact: dict[str, Any] | None = None  # несовместимый код: факт о конструкции с цитатой (issue #40 п. 3)


def _design_fact(compat: Any) -> dict[str, Any] | None:
    """Факт о конструкции из ячейки матрицы «узла нет»: что именно отсутствует и цитата-основание со страницей."""
    if not compat.doc:
        return None
    doc = DOCS_BY_ID.get(compat.doc)
    return {
        "text": compat.why[:1].upper() + compat.why[1:] + ".",
        "quote": compat.quote,
        "manual": doc.designation if doc else compat.doc,
        "pdf_page": compat.page,
        "url": f"/manuals/{compat.doc}#page={compat.page}",
    }


def _pct(value: float | None) -> int | None:
    return None if value is None else round(value * 100)


def build_card(diag: Diagnosis, fault_titles: dict[str, str], engine: str | None = None) -> VerdictCard:
    banners: list[str] = []
    if diag.signal_quality == "warning":
        banners.append(BANNER_NOISY)

    if diag.status == "check_failed" or diag.signal_quality == "bad":
        # Никаких выводов о двигателе: ни кода, ни уверенности, ни заявки.
        return VerdictCard(
            status=diag.status,
            color="grey",
            title="Проверка не удалась",
            action="Выводов о двигателе нет. Повторите запись звука: прогрейте двигатель, "
            "дождитесь ровного холостого хода и запишите снова.",
            banners=[BANNER_BAD] if diag.status != "check_failed" else [],
            ticket_possible=False,
            fault_code=None,
            fault_title=None,
            confidence_pct=None,
            ml_quote=diag.description,
            ml_quote_label="Причина отбраковки (сообщение сервиса диагностики)",
        )

    if diag.status == "normal":
        early = diag.anomaly_score is not None and diag.anomaly_score >= EARLY_RECHECK_SCORE
        if early:
            banners.append(BANNER_EARLY_RECHECK)
        return VerdictCard(
            status="normal",
            color="yellow" if early else "green",
            title="Двигатель в норме",
            action="Можно продолжать работу. Заявка не нужна."
            + (" Сделайте повторную проверку раньше планового срока." if early else ""),
            banners=banners,
            ticket_possible=False,
            fault_code=None,
            fault_title=None,
            confidence_pct=_pct(diag.confidence),
            ml_quote=diag.description,
            ml_quote_label="Сообщение сервиса диагностики",
        )

    # anomaly: название — из нашего справочника по коду, а не из текста ответа.
    code = diag.anomaly_type
    title = fault_titles.get(code) if code else None
    known = title is not None
    if known and code and engine:
        compat = compat_check(code, engine)
        if not compat.ok:
            return VerdictCard(
                status="anomaly",
                color="grey",
                title="Результат не подходит к этому двигателю",
                action=f"Сервис указал «{title}», но {compat.why} ({engine}). "
                "Скорее всего, ошибка записи: повторите проверку. Заявку по такому результату не оформляем.",
                banners=banners,
                ticket_possible=False,
                compatible=False,
                fault_code=code,
                fault_title=title,
                confidence_pct=_pct(diag.confidence),
                ml_quote=diag.description,
                ml_quote_label="Сообщение сервиса диагностики",
                design_fact=_design_fact(compat),
            )
    urgency, reason = urgency_for(diag) if known else (None, None)
    return VerdictCard(
        status="anomaly",
        color="red",
        title=f"Неисправность: {title}" if known else "Неисправность неизвестного типа",
        action=URGENCY_ACTION[urgency]
        if urgency
        else "Тип неисправности не распознан. Повторите проверку; заявку по такому результату не оформляем.",
        urgency=urgency,
        urgency_reason=reason,
        banners=banners,
        ticket_possible=known,
        fault_code=code if known else None,
        fault_title=title,
        confidence_pct=_pct(diag.confidence),
        ml_quote=diag.description,
        ml_quote_label="Сообщение сервиса диагностики",
    )
