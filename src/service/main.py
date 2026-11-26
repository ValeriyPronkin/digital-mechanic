"""HTTP-сервис: страница механика (/), /health и API парка и диагностики."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from service import __version__, conv_state, kb_store
from service.agent import Agent
from service.clients import MLClient, ServiceError, ToirClient
from service.fleet import fleet
from service.llm import provider_from_env
from service.manual_search import default_searcher, manual_pdf
from service.rate_limit import RateLimiter, client_key
from service.store import Store
from service.verdict_policy import VerdictCard, build_card


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Стенд: индекс руководств из бакета S3_BUCKET по IAM-токену (D-9, #6) — до первого вопроса механика.
    kb_store.ensure_index_from_env()
    yield


app = FastAPI(title="Цифровой механик", version=__version__, lifespan=lifespan)
INDEX_HTML = Path(__file__).parent / "static" / "index.html"


@lru_cache(maxsize=1)
def ml_client() -> MLClient:
    return MLClient()


@lru_cache(maxsize=1)
def store() -> Store:
    return Store()


@lru_cache(maxsize=1)
def agent() -> Agent:
    return Agent(
        provider=provider_from_env(),
        ml=ml_client(),
        toir=ToirClient(),
        searcher=default_searcher(),
        store=store(),
        fleet=fleet(),
        budget_day_rub=float(os.environ.get("LLM_BUDGET_DAY_RUB", "100")),
        budget_total_rub=float(os.environ.get("LLM_BUDGET_TOTAL_RUB", "1000")),
    )


@lru_cache(maxsize=1)
def limiter() -> RateLimiter:
    return RateLimiter.from_env()


def _rate_limit(request: Request) -> None:
    wait = limiter().check(client_key(request))
    if wait > 0:
        raise HTTPException(
            429,
            f"Слишком много вопросов подряд. Подождите {int(wait) + 1} с и спросите снова.",
            headers={"Retry-After": str(int(wait) + 1)},
        )


@app.get("/health")
def health() -> dict[str, Any]:
    """Сервис жив. Ключи не раскрываются — только факт их наличия."""
    return {
        "status": "ok",
        "version": __version__,
        "llm_key_present": any(os.environ.get(k) for k in ("DEEPSEEK_API_KEY", "GIGACHAT_CREDENTIALS", "LLM_API_KEY")),
        "llm_provider": os.environ.get("LLM_PROVIDER", "deepseek"),
        "manuals_index": manuals_index_status(),
    }


def manuals_index_status() -> dict[str, Any]:
    """Есть ли индекс руководств у экземпляра: версия из бакета и число фрагментов (без загрузки поиска)."""
    from service.manuals.index import index_dir

    frags = index_dir() / "fragments.jsonl"
    if not frags.is_file():
        return {"present": False}
    with frags.open("rb") as f:
        count = sum(1 for _ in f)
    return {"present": True, "version": kb_store.installed_version(index_dir()), "fragments": count}


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
    vehicle = fleet().vehicle(req.vehicle_id)
    card = build_card(diag, fleet().fault_titles, vehicle.engine_model if vehicle else None)
    store().remember_view(req.vehicle_id, req.session_id, card.status, card.fault_code)
    return card


class ChatIn(BaseModel):
    vehicle_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)
    state: str | None = Field(default=None, max_length=400_000)  # подписанное состояние разговора


@app.post("/api/chat")
def chat(req: ChatIn, request: Request) -> dict[str, Any]:
    """Вопрос механика агенту. Разговор привязан к машине и проверке: сменились — новый разговор.
    Состояние разговора хранит клиент (подписанная строка), поэтому любой экземпляр стенда продолжит его."""
    _rate_limit(request)
    try:
        ag = agent()
        conv = conv_state.load(req.state, fleet()) if req.state else None
        if conv is None or conv.vehicle.vehicle_id != req.vehicle_id or conv.session_id != req.session_id:
            conv = ag.start(req.vehicle_id, req.session_id)
        reply = ag.ask(conv, req.message)
    except ServiceError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    return {"conversation_id": conv.id, "state": conv_state.dump(conv), **reply.__dict__}


class TicketIn(BaseModel):
    state: str = Field(min_length=1, max_length=400_000)
    fingerprint: str = Field(min_length=1)


@app.post("/api/tickets", status_code=201)
def send_ticket(req: TicketIn, request: Request) -> dict[str, Any]:
    """Отправка в ТОиР показанного черновика: только если отпечаток совпал с последним черновиком разговора."""
    _rate_limit(request)
    try:
        conv = conv_state.load(req.state, fleet())
        resp = agent().confirm_ticket(conv, req.fingerprint)
    except ServiceError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    return {**resp.model_dump(), "state": conv_state.dump(conv)}


@app.get("/manuals/{manual_id}")
def manual(manual_id: str) -> FileResponse:
    """PDF руководства для ссылки «документ, страница» (страница — якорем #page=N)."""
    path = manual_pdf(manual_id)
    if path is None:
        raise HTTPException(404, "Файл руководства недоступен на этом сервере.")
    return FileResponse(path, media_type="application/pdf")
