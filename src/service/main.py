"""HTTP-сервис: страница механика (/), /health и API парка и диагностики."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from service import (
    IMPORT_STARTED,
    INSTANCE_ID,
    __version__,
    api_v2,
    conv_state,
    kb_store,
    language,
    passport,
    stand_log,
)
from service import parts_supplier as parts_supplier_mod
from service.agent import Agent, Level
from service.clients import MLClient, ServiceError, ToirClient
from service.fault_matrix import card_explanation
from service.fleet import fleet
from service.fleet_api import build_router as build_fleet_router
from service.llm import provider_from_env
from service.manual_search import default_searcher, manual_pdf
from service.page_marks import PageMarks
from service.pages import PageImages
from service.rate_limit import RateLimiter, client_key
from service.spend import BucketObject, RefreshingIamAuth, SharedLedger
from service.store import Store
from service.verdict_policy import VerdictCard, build_card
from service.voice import (
    DEFAULT_VOICE,
    NOT_HEARD,
    SpeechClient,
    SpeechKit,
    TtsCache,
    choose_tts_api,
    pcm_from_wav,
    speech_for,
    speech_lang,
    spoken_text,
    stt_cost_rub,
    timed,
    tts_cost_rub,
)

STARTUP: dict[str, float] = {}

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Стенд: индекс руководств из бакета S3_BUCKET по IAM-токену (D-9, #6) — до первого вопроса механика.
    STARTUP["import_s"] = round(time.monotonic() - IMPORT_STARTED, 2)
    t = time.monotonic()
    kb_store.ensure_index_from_env()
    STARTUP["index_fetch_s"] = round(time.monotonic() - t, 2)
    STARTUP["ready_at"] = time.monotonic()
    slog = journal()
    if slog is not None:  # стенд: свой журнал в бакете (#27)
        slog.start(version=__version__, provider=os.environ.get("LLM_PROVIDER", ""))
        slog.run_background()
    yield
    if slog is not None:
        slog.close()


app = FastAPI(title="Цифровой механик", version=__version__, lifespan=lifespan)


@lru_cache(maxsize=1)
def journal() -> stand_log.StandLog | None:
    return stand_log.from_env(INSTANCE_ID)


@app.middleware("http")
async def log_requests(request: Request, call_next: Any) -> Any:
    """Журнал стенда (#27): маршрут без параметров, метод, код, время; исключение — только класс."""
    slog = journal()
    t0 = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        if slog is not None:
            slog.event("error", route=stand_log.route_template(request), method=request.method,
                       error=type(exc).__name__, status=500, ms=int((time.monotonic() - t0) * 1000))  # fmt: skip
            await asyncio.to_thread(slog.maybe_flush)
        raise
    if slog is not None and request.url.path != "/health":
        slog.event("request", route=stand_log.route_template(request), method=request.method,
                   status=response.status_code, ms=int((time.monotonic() - t0) * 1000))  # fmt: skip
    if slog is not None:
        # выгрузка — пока у экземпляра есть процессор (до ответа); не чаще раза в FLUSH_S, ошибка — сразу
        await asyncio.to_thread(slog.maybe_flush)
    return response


STEP_NAMES = {"get_diagnosis": "diagnose", "search_manual": "search", "draft_ticket": "ticket",
              "fleet_summary": "fleet", "vehicle_history": "history"}  # fmt: skip


def log_steps(trace: dict[str, Any]) -> None:
    """Шаги агента — в журнал стенда: имя шага обезличено (diagnose, search, model…), без текста и номеров."""
    slog = journal()
    if slog is None:
        return
    for st in trace.get("steps", []):
        name = str(st.get("name", ""))
        if st.get("kind") == "llm":
            step = "plan" if "план поиска" in name else "model"
        elif st.get("kind") == "cache":
            step = "answer_cache"
        else:
            step = STEP_NAMES.get(name.replace(" (код)", ""), "tool")
        slog.event("step", step=step, ms=st.get("ms"), ok=st.get("ok", True))


INDEX_HTML = Path(__file__).parent / "static" / "index.html"
# Интерфейс v2 (issue #52): сборка React/Vite из web/ (автор — Никита Пронкин), раздаётся по /v2.
WEB_DIST = Path(os.environ.get("WEB_DIST", str(Path(__file__).resolve().parents[2] / "web" / "dist")))


def _v2_file(path: str) -> Path | None:
    """Файл сборки v2 или index.html для маршрутов приложения; None — сборки нет. Выход за каталог запрещён."""
    if not (WEB_DIST / "index.html").is_file():
        return None
    root = WEB_DIST.resolve()
    target = (WEB_DIST / path).resolve() if path else root / "index.html"
    if root not in target.parents and target != root / "index.html":
        return root / "index.html"
    return target if target.is_file() else root / "index.html"


@app.get("/v2", include_in_schema=False)
@app.get("/v2/{path:path}", include_in_schema=False)
def v2(path: str = "") -> FileResponse:
    f = _v2_file(path)
    if f is None:
        raise HTTPException(404, "Интерфейс v2 не собран: make web (или образ Docker).")
    # Файлы с хэшем в имени (assets/) кэшируются надолго, index.html — нет: новая сборка видна сразу.
    cache = "public, max-age=31536000, immutable" if "/assets/" in f.as_posix() else "no-cache"
    return FileResponse(f, headers={"Cache-Control": cache})


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
        ledger=shared_ledger(),
    )


def shared_ledger() -> SharedLedger | None:
    """Стенд (задан S3_BUCKET): общий счётчик расходов в бакете по IAM-токену (#11). Локально — журнал SQLite."""
    if not os.environ.get("S3_BUCKET", "").strip() or os.environ.get("SPEND_LEDGER", "bucket") != "bucket":
        return None
    http = httpx.Client()
    endpoint = os.environ.get("S3_ENDPOINT", kb_store.DEFAULT_ENDPOINT)
    bucket = kb_store.Bucket(os.environ["S3_BUCKET"].strip(), RefreshingIamAuth(http), http, endpoint)
    return SharedLedger(BucketObject(bucket))


@lru_cache(maxsize=1)
def speech() -> SpeechClient:
    return SpeechKit.from_env()


@lru_cache(maxsize=1)
def tts_cache() -> TtsCache:
    return TtsCache.from_env()


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


app.include_router(build_fleet_router(lambda: store()))  # /fleet — главный механик (#21)


@app.get("/health")
def health() -> dict[str, Any]:
    """Сервис жив. Ключи не раскрываются — только факт их наличия."""
    return {
        "status": "ok",
        "version": __version__,
        "llm_key_present": any(os.environ.get(k) for k in ("DEEPSEEK_API_KEY", "GIGACHAT_CREDENTIALS", "LLM_API_KEY")),
        "llm_provider": os.environ.get("LLM_PROVIDER", "deepseek"),
        "manuals_index": manuals_index_status(),
        "voice_key_present": any(os.environ.get(k) for k in ("YANDEX_TTS_API_KEY", "YANDEX_API_KEY")),
        "tts_voice": os.environ.get("TTS_VOICE", DEFAULT_VOICE),
        "instance": {
            "id": INSTANCE_ID,
            "uptime_s": round(time.monotonic() - IMPORT_STARTED, 1),
            **{k: v for k, v in STARTUP.items() if k != "ready_at"},
        },
    }


def manuals_index_status() -> dict[str, Any]:
    """Есть ли индекс руководств у экземпляра: версия из бакета и число фрагментов (без загрузки поиска)."""
    from service.manuals.index import index_dir

    frags = index_dir() / "fragments.jsonl"
    if not frags.is_file():
        return {"present": False}
    with frags.open("rb") as f:
        count = sum(1 for _ in f)
    semantic = (index_dir() / "vectors.npy").is_file() and all(
        os.environ.get(k, "").strip() for k in ("YANDEX_API_KEY", "YANDEX_FOLDER_ID")
    )
    return {
        "present": True,
        "version": kb_store.installed_version(index_dir()),
        "fragments": count,
        "semantic": semantic,  # поиск по смыслу: есть векторы и ключ Yandex для эмбеддинга вопроса
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def parts_supplier() -> parts_supplier_mod.PartsSupplier:
    return parts_supplier_mod.from_env()


@app.get("/api/parts")
def parts_lookup(q: str) -> dict[str, Any]:
    """Поставщик запчастей по обозначению или наименованию: наличие, цена, срок — если поставщик подключён
    (PARTS_SUPPLIERS — файлы поставщиков, опрос параллельно; прежний PARTS_SUPPLIER=csv|http); по умолчанию —
    «каталог не подключён» (STUB: parts-catalog)."""
    query = q.strip()[:120]
    if not query:
        raise HTTPException(status_code=422, detail="Пустой запрос.")
    return {"query": query, **parts_supplier().find(query).public()}


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
    t0 = time.monotonic()
    try:
        diag = ml_client().diagnose(req.vehicle_id, req.session_id)
    except ServiceError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    ml_ms = int((time.monotonic() - t0) * 1000)
    if diag.vehicle_id != req.vehicle_id or diag.session_id != req.session_id:
        raise HTTPException(502, "Сервис диагностики вернул результат для другой проверки.")
    vehicle = fleet().vehicle(req.vehicle_id)
    card = build_card(
        diag, fleet().fault_titles, vehicle.engine_model if vehicle else None, vehicle.sessions if vehicle else None
    )
    if card.status == "anomaly" and card.compatible and card.fault_code and vehicle:
        card.manual = card_explanation(card.fault_code, vehicle.engine_model)
    store().remember_view(req.vehicle_id, req.session_id, card.status, card.fault_code)
    card.passport = passport.for_card(card, ml_ms)
    return card


class ChatIn(BaseModel):
    vehicle_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)
    level: Level = "steps"  # уровень механика (#17): «Опытный» / «Пошагово»
    stt_id: int | None = None  # вопрос голосом: запись журнала распознавания (#31 — паспорт запроса)
    lang: str | None = Field(default=None, max_length=10)  # язык ответа: ru, uz, uz-cyrl, tg, kk, ky, en; нет — вопроса
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
        reply = ag.ask(conv, req.message, req.level, req.lang)
    except ServiceError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    log_steps(reply.trace)
    spoken = speech_for(reply.text, conv.sources, reply.lang)
    stt = store().voice_call(req.stt_id) if req.stt_id else None
    stt = stt if stt and stt.get("kind") == "stt" else None
    pp = passport.build(
        reply.trace,
        question=req.message,
        notes=reply.notes,
        by_voice=stt is not None,
        stt=stt,
        speech_text=spoken.text,
        level=req.level,
    )
    slog = journal()
    passport.write(pp, time.time(), put=slog.put if slog is not None else None)  # журнал стенда (#27)
    return {
        "conversation_id": conv.id,
        "state": conv_state.dump(conv),
        **reply.__dict__,
        # Короткая версия для ответа вслух (#14): собрана кодом, цифры сверены с фрагментом; синтез — по подписи.
        "speech": {"text": spoken.text, "sig": conv_state.sign_text(spoken.text), "lang": speech_lang(reply.lang)},
        "passport": pp,  # «?» у ответа (#31): шаги, контекст, токены, ₽
    }


@app.post("/api/voice/recognize")
async def voice_recognize(request: Request, lang: str = "ru") -> dict[str, Any]:
    """Вопрос голосом: WAV 16 кГц моно (до 30 с) → текст. Текст механик видит и может поправить до отправки.
    `?lang=uz|kk|en` — язык распознавания (выбор механика); по умолчанию и без распознавания на языке — русский."""
    _rate_limit(request)
    body = await request.body()
    try:
        pcm, seconds = pcm_from_wav(body)
        text, ms = timed(speech().recognize, pcm, language.normalize(lang) or "ru")
    except ServiceError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    cost = stt_cost_rub(seconds)
    stt_id = store().log_voice("stt", round(seconds, 2), cost, ms)
    if (slog := journal()) is not None:
        slog.event("step", step="stt", ms=ms)
    if not text:
        raise HTTPException(422, NOT_HEARD)
    return {"text": text, "seconds": round(seconds, 1), "cost_rub": round(cost, 3), "stt_id": stt_id}


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    sig: str = Field(min_length=64, max_length=64)
    lang: str | None = Field(default=None, max_length=10)  # язык ответа из `speech.lang`; нет — по буквам текста


@app.post("/api/voice/speak")
def voice_speak(req: SpeakIn, request: Request) -> Response:
    """Ответ вслух: mp3 короткой версии. Только текст с подписью сервера — синтеза произвольного текста нет."""
    _rate_limit(request)
    if not conv_state.verify_text(req.text, req.sig):
        raise HTTPException(400, "Этот текст сервер не готовил к озвучке.")
    lang = speech_lang(language.normalize(req.lang) or language.detect(req.text))
    chars = len(spoken_text(req.text, lang))  # тарифицируется текст, который уходит в синтез (единицы — словами)
    t0 = time.monotonic()
    audio = tts_cache().get(req.text, lang)
    if audio is not None:  # одинаковая фраза уже синтезирована — 0 ₽
        store().log_voice("tts_cache", chars, 0.0, int((time.monotonic() - t0) * 1000))
        return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store", "X-TTS": "cache"})
    api = choose_tts_api(chars)
    try:
        audio, ms = timed(speech().synthesize, req.text, api, lang)
    except ServiceError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    tts_cache().put(req.text, audio, lang)
    store().log_voice("tts", chars, tts_cost_rub(chars, api), ms)
    if (slog := journal()) is not None:
        slog.event("step", step="tts", ms=ms)
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store", "X-TTS": api})


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


@app.get("/manuals/{manual_id}/page/{page}.png")
def manual_page_image(manual_id: str, page: int) -> Response:
    """Картинка страницы PDF для «как в руководстве» (#17). Только если PDF есть на этом сервере."""
    path = manual_pdf(manual_id)
    if path is None:
        raise HTTPException(404, "Файл руководства недоступен на этом сервере.")
    png = render_page_png(str(path), page)
    if png is None:
        raise HTTPException(404, f"В руководстве нет страницы {page}.")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@lru_cache(maxsize=32)
def render_page_png(path: str, page: int) -> bytes | None:
    import io

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        if not 1 <= page <= len(pdf):
            return None
        image = pdf[page - 1].render(scale=1.6).to_pil()
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    finally:
        pdf.close()


@app.get("/manuals/{manual_id}")
def manual(manual_id: str) -> FileResponse:
    """PDF руководства для ссылки «документ, страница» (страница — якорем #page=N)."""
    path = manual_pdf(manual_id)
    if path is None:
        raise HTTPException(404, "Файл руководства недоступен на этом сервере.")
    return FileResponse(path, media_type="application/pdf")


@lru_cache(maxsize=1)
def page_images() -> PageImages:
    return PageImages.from_env()


@lru_cache(maxsize=1)
def page_marks() -> PageMarks:
    """Строки страниц для подсветки цитаты: бакет marks/ (тот же доступ, что у картинок) или локальный PDF."""
    return PageMarks(page_images().bucket)


@app.get("/manuals/{manual_id}/page/{page}.webp")
def manual_page_webp(manual_id: str, page: int) -> Response:
    """Картинка страницы руководства (WebP) для просмотрщика v2: бакет `pages/` или рендер из PDF; кэш на сутки."""
    data = page_images().get(manual_id, page)
    if data is None:
        raise HTTPException(404, "Картинки этой страницы нет — смотрите текст страницы.")
    return Response(content=data, media_type="image/webp", headers={"Cache-Control": "public, max-age=86400"})


# Интерфейс v2 (issue #52): его API — /api/v2 поверх нашей логики (слой совместимости `api_v2`).
app.include_router(
    api_v2.build_router(
        lambda: agent(),
        lambda: store(),
        lambda: fleet(),
        _rate_limit,
        api_v2.ThreadStore.from_env(),
        lambda: speech(),
        lambda: page_images(),
        lambda: page_marks(),
        lambda: slog.put if (slog := journal()) is not None else None,
        get_parts=lambda: parts_supplier(),
    )
)
