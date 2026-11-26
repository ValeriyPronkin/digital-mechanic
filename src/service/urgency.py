"""Срочность заявки по результату проверки — правило в коде, с основанием.

Общее для агента (срочность заявки) и сводки главного механика (карантин, issue #21).
"""

from __future__ import annotations

from typing import Literal

from service.clients import Diagnosis

Urgency = Literal["low", "medium", "high"]

CRITICAL_CODES = {"F02": "низкое давление масла", "F03": "перегрев / жидкость в масле", "F14": "цепь ГРМ"}


def urgency_for(diag: Diagnosis) -> tuple[Urgency, str]:
    """Срочность заявки — правило в коде, с основанием."""
    code = diag.anomaly_type or ""
    if code in CRITICAL_CODES:
        return "high", f"{code}: {CRITICAL_CODES[code]} — работа двигателя грозит серьёзной поломкой"
    if (diag.anomaly_score or 0) >= 0.85:
        return "high", f"высокая оценка отклонения ({diag.anomaly_score:.2f})"
    if (diag.confidence or 0) < 0.6 or diag.signal_quality == "warning":
        return "low", "уверенность сервиса диагностики снижена — сначала уточнить дефектовкой"
    return "medium", "отклонение подтверждено, критичных признаков нет"
