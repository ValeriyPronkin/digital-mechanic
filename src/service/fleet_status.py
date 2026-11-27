"""Режим «Главный механик» (ТЗ B3, сценарий С4) и график оценки (B2), issue #21.

Статус машины — по последней проверке, правилом в коде (не моделью):
  карантин         — отклонение с высокой срочностью (`verdict_policy.urgency_for`: F02, F03, F14 или оценка ≥ 0,85)
                     или код, несовместимый с двигателем (узла нет — результату нельзя верить, машину не выпускать
                     до повторной проверки);
  требует внимания — прочие отклонения; запись с помехами (signal_quality = warning);
                     норма с оценкой ≥ 0,30 (CLAUDE.md, правило 7: «норма, но повторить проверку раньше срока»);
  нужна перезапись — check_failed: выводов о двигателе нет;
  норма            — остальное.
Тенденция оценки — по последним 3–5 проверкам: последняя оценка против среднего предыдущих; сбой — разрыв,
а не ноль. Снижение не значит «исправно»: оценка — признак, а не диагноз.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from service.compat import check as compat_check
from service.fleet import Fleet, Session, Vehicle
from service.verdict_policy import urgency_for

Status = Literal["quarantine", "attention", "rerecord", "normal"]

STATUS_LABEL: dict[str, str] = {
    "quarantine": "Карантин",
    "attention": "Требует внимания",
    "rerecord": "Нужна перезапись",
    "normal": "Норма",
}
PRIORITY: dict[str, int] = {"quarantine": 0, "attention": 1, "rerecord": 2, "normal": 3}

ATTENTION_SCORE = 0.30  # норма с оценкой не ниже — повторить проверку раньше срока (правило 7)
TREND_POINTS = 5  # сколько последних проверок на графике
TREND_DELTA = 0.10  # изменение оценки, которое считаем тенденцией, а не шумом

TREND_UP = "растёт"
TREND_DOWN = "снижается — это не значит исправно"
TREND_FLAT = "стабильно"
TREND_FEW = "мало точек для тенденции"


@dataclass
class VehicleStatus:
    status: Status
    reasons: list[str] = field(default_factory=list)
    last: Session | None = None


def _ru(text: str) -> str:
    """0.93 → 0,93: механик читает по-русски."""
    return re.sub(r"(?<=\d)\.(?=\d)", ",", text)


def ordered(v: Vehicle) -> list[Session]:
    return sorted(v.sessions, key=lambda s: s.checked_at)


def vehicle_status(v: Vehicle, fault_titles: dict[str, str] | None = None) -> VehicleStatus:
    sessions = ordered(v)
    if not sessions:
        return VehicleStatus("rerecord", ["проверок ещё не было"])
    last = sessions[-1]
    titles = fault_titles or {}
    if last.status == "check_failed":
        return VehicleStatus("rerecord", ["последняя проверка не удалась — выводов о двигателе нет"], last)
    if last.status == "anomaly":
        code = last.anomaly_type or ""
        title = titles.get(code, "")
        name = title or code or "отклонение"  # код F.. механику не нужен: он есть в карточке
        compat = compat_check(code, v.engine_model) if code else None
        if compat is not None and not compat.ok:
            return VehicleStatus(
                "quarantine", [f"{name}: {compat.why} — результату верить нельзя, нужна повторная проверка"], last
            )
        urgency, why = urgency_for(last)
        why = why.split(". Чем грозит")[0]  # строка парка — только основание; угроза — на карточке
        why = _ru(why.removeprefix(f"{code}: "))
        why = why[:1].lower() + why[1:]  # «Клапанный механизм: оценка отклонения 0,93, …» — одна строка
        if urgency == "high":
            return VehicleStatus("quarantine", [f"{name}: {why}"], last)
        reasons = [f"{name}: {why}"]
        if last.signal_quality == "warning":
            reasons.append("запись с помехами, уверенность снижена")
        return VehicleStatus("attention", reasons, last)
    reasons = []
    if last.signal_quality == "warning":
        reasons.append("запись с помехами, уверенность снижена")
    if (last.anomaly_score or 0) >= ATTENTION_SCORE:
        score = _ru(f"{last.anomaly_score:.2f} ≥ {ATTENTION_SCORE:.2f}")
        reasons.append(f"норма, но оценка {score} — повторить проверку раньше срока")
    if reasons:
        return VehicleStatus("attention", reasons, last)
    return VehicleStatus("normal", [], last)


def trend(v: Vehicle, points: int = TREND_POINTS) -> dict[str, Any]:
    """Точки графика (сбой — разрыв: score = None) и подпись тенденции."""
    window = ordered(v)[-points:]
    pts = [
        {
            "session_id": s.session_id,
            "checked_at": s.checked_at,
            "status": s.status,
            "score": None if s.status == "check_failed" else s.anomaly_score,
        }
        for s in window
    ]
    values: list[float] = [
        float(s.anomaly_score) for s in window if s.status != "check_failed" and s.anomaly_score is not None
    ]
    if len(values) < 2:
        return {"points": pts, "trend": TREND_FEW, "delta": None}
    prev = values[:-1]
    delta = values[-1] - sum(prev) / len(prev)
    label = TREND_UP if delta >= TREND_DELTA else TREND_DOWN if delta <= -TREND_DELTA else TREND_FLAT
    return {"points": pts, "trend": label, "delta": round(delta, 3)}


def row(v: Vehicle, st: VehicleStatus) -> dict[str, Any]:
    last = st.last
    return {
        "vehicle_id": v.vehicle_id,
        "garage_no": v.garage_no,
        "name": v.display_name,
        "engine_model": v.engine_model,
        "status": st.status,
        "status_label": STATUS_LABEL[st.status],
        "reasons": st.reasons,
        "last_session": last.session_id if last else None,
        "last_checked_at": last.checked_at if last else None,
        "fault_code": last.anomaly_type if last else None,
        "anomaly_score": last.anomaly_score if last else None,
    }


def summary(fleet: Fleet) -> dict[str, Any]:
    """Сводка по парку: счётчики и приоритетный список (карантин → внимание → перезапись), у строки — почему."""
    rows = [row(v, vehicle_status(v, fleet.fault_titles)) for v in fleet.vehicles]
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in PRIORITY}
    priority = sorted(
        (r for r in rows if r["status"] != "normal"),
        key=lambda r: (PRIORITY[r["status"]], -(r["anomaly_score"] or 0), r["vehicle_id"]),
    )
    return {
        "total": len(rows),
        "counts": counts,
        "labels": STATUS_LABEL,
        "priority": priority,
        "normal": sorted((r for r in rows if r["status"] == "normal"), key=lambda r: r["vehicle_id"]),
        "rule": {
            "attention_score": ATTENTION_SCORE,
            "trend_points": TREND_POINTS,
            "trend_delta": TREND_DELTA,
        },
    }
