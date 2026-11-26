"""API и страница «Главный механик» (issue #21): /fleet, /api/fleet, /api/fleet/{vehicle_id}.

Отдельный модуль и своя страница — чтобы не пересекаться с голосом на главной. Всё — кодом, без модели.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from service.fleet import fleet
from service.fleet_status import ordered, row, summary, trend, vehicle_status
from service.store import Store

PAGE = Path(__file__).parent / "static" / "fleet.html"


def build_router(store: Callable[[], Store]) -> APIRouter:
    router = APIRouter()

    @router.get("/fleet", response_class=HTMLResponse)
    def fleet_page() -> str:
        return PAGE.read_text(encoding="utf-8")

    @router.get("/api/fleet")
    def fleet_summary() -> dict[str, Any]:
        return summary(fleet())

    @router.get("/api/fleet/{vehicle_id}")
    def fleet_vehicle(vehicle_id: str) -> dict[str, Any]:
        f = fleet()
        v = f.vehicle(vehicle_id)
        if v is None:
            raise HTTPException(404, f"Машина {vehicle_id} не найдена в парке.")
        history = [
            {
                "session_id": s.session_id,
                "checked_at": s.checked_at,
                "status": s.status,
                "fault_code": s.anomaly_type,
                "fault_title": f.fault_titles.get(s.anomaly_type or "", None),
                "anomaly_score": s.anomaly_score,
                "confidence": s.confidence,
                "signal_quality": s.signal_quality,
            }
            for s in reversed(ordered(v))
        ]
        return {
            **row(v, vehicle_status(v, f.fault_titles)),
            "history": history,
            "trend": trend(v),
            "tickets": store().vehicle_memory(vehicle_id)["tickets"],
        }

    return router
