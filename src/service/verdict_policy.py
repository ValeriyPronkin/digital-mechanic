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

EARLY_RECHECK_SCORE = 0.30

Color = Literal["green", "yellow", "red", "grey"]

BANNER_NOISY = "Запись с помехами, уверенность снижена."
BANNER_BAD = "Запись непригодна для выводов."
BANNER_EARLY_RECHECK = "Норма, но повторите проверку раньше срока."


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
            )
    return VerdictCard(
        status="anomaly",
        color="red",
        title=f"Неисправность: {title}" if known else "Неисправность неизвестного типа",
        action="Не откладывайте: машине нужна дефектовка. Можно оформить заявку."
        if known
        else "Тип неисправности не распознан. Повторите проверку; заявку по такому результату не оформляем.",
        banners=banners,
        ticket_possible=known,
        fault_code=code if known else None,
        fault_title=title,
        confidence_pct=_pct(diag.confidence),
        ml_quote=diag.description,
        ml_quote_label="Сообщение сервиса диагностики",
    )
