"""HTTP-сервис: страница механика (/), /health и API парка и диагностики."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from service import __version__
from service.clients import MLClient, ServiceError
from service.fleet import fleet
from service.verdict_policy import VerdictCard, build_card

app = FastAPI(title="Цифровой механик", version=__version__)
INDEX_HTML = Path(__file__).parent / "static" / "index.html"


@lru_cache(maxsize=1)
def ml_client() -> MLClient:
    return MLClient()


@app.get("/health")
def health() -> dict[str, Any]:
    """Сервис жив. Ключи не раскрываются — только факт их наличия."""
    return {
        "status": "ok",
        "version": __version__,
        "llm_key_present": bool(os.environ.get("LLM_API_KEY")),
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/api/vehicles")
def list_vehicles() -> list[dict[str, Any]]:
    """Список ТС для выбора: госномер, гаражный номер, марка/модель, двигатель, число проверок."""
    return [
        {
            "vehicle_id": v.vehicle_id,
            "garage_no": v.garage_no,
            "name": v.display_name,
            "make": v.make,
            "model": v.model,
            "vehicle_type": v.vehicle_type,
            "engine_model": v.engine_model,
            "fuel": v.fuel,
            "sessions_count": len(v.sessions),
            "last_checked_at": v.sessions[-1].checked_at if v.sessions else None,
        }
        for v in fleet().vehicles
    ]


@app.get("/api/vehicles/{vehicle_id}")
def vehicle_history(vehicle_id: str) -> dict[str, Any]:
    """Карточка ТС и история проверок (новые сверху). Результат проверки здесь не раскрывается:
    его даёт /api/diagnose через сервис диагностики."""
    v = fleet().vehicle(vehicle_id)
    if v is None:
        raise HTTPException(404, f"Машина {vehicle_id} не найдена в парке.")
    return {
        "vehicle_id": v.vehicle_id,
        "garage_no": v.garage_no,
        "name": v.display_name,
        "vehicle_type": v.vehicle_type,
        "engine_model": v.engine_model,
        "fuel": v.fuel,
        "sessions": [{"session_id": s.session_id, "checked_at": s.checked_at} for s in reversed(v.sessions)],
    }


class DiagnoseIn(BaseModel):
    vehicle_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


@app.post("/api/diagnose")
def diagnose(req: DiagnoseIn) -> VerdictCard:
    """Результат проверки из Mock ML → карточка вердикта по правилам (без модели)."""
    if fleet().vehicle(req.vehicle_id) is None:
        raise HTTPException(404, f"Машина {req.vehicle_id} не найдена в парке.")
    try:
        diag = ml_client().diagnose(req.vehicle_id, req.session_id)
    except ServiceError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    if diag.vehicle_id != req.vehicle_id or diag.session_id != req.session_id:
        raise HTTPException(502, "Сервис диагностики вернул результат для другой проверки.")
    return build_card(diag, fleet().fault_titles)
