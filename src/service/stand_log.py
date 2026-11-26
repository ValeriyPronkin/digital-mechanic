"""Журнал стенда в частном бакете (issue #27): Cloud Logging Yandex отключает с 01.12.2026, стенд живёт до 03.12.

  logs/<дата по Москве>/<экземпляр>.jsonl — строка на событие:
    {"ts", "kind": "start" | "request" | "step" | "error", ...только разрешённые поля}

Что пишется: старт экземпляра и аптайм, метод/маршрут/код/время запроса, время шагов агента (диагноз, поиск, модель,
речь), класс ошибки. Чего нет: текста вопросов и ответов, номеров машин, ФИО, телефонов — поля проходят через
белый список, а маршрут — без параметров (`/api/fleet/{id}`, а не номер машины).

Пишет экземпляр сам, пачками (раз в FLUSH_S или при BATCH событиях), по IAM-токену сервисного аккаунта стенда —
тот же механизм, что общий счётчик расходов (#11). S3 не дописывает в объект, поэтому экземпляр держит события
своих суток в памяти и перезаписывает свой файл целиком: писатель у файла один, конфликтов нет. Сбой бакета журнал
не роняет и сервис не задевает: события подождут следующей записи (не больше MAX_EVENTS в памяти).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from service.spend import MSK

log = logging.getLogger(__name__)

PREFIX = "logs"
FLUSH_S = 60.0
BATCH = 200
MAX_EVENTS = 50_000  # сутки экземпляра с запасом; дальше старые события дня выбрасываются
KINDS = ("start", "request", "step", "error")
# Белый список полей: ничего из вопроса, ответа или карточки машины
FIELDS = {"route", "method", "status", "ms", "step", "ok", "error", "uptime_s", "version", "provider", "cache"}


def instance_id() -> str:
    host = socket.gethostname().split(".")[0][:24] or "local"
    return f"{host}-{uuid.uuid4().hex[:6]}"


class StandLog:
    def __init__(
        self,
        put: Callable[[str, bytes], None],
        instance: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.put, self.clock = put, clock
        self.instance = instance or instance_id()
        self.started = clock()
        self._lock = threading.Lock()
        self._day = ""
        self._events: list[str] = []
        self._unsent = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- запись событий ----
    def event(self, kind: str, **fields: Any) -> None:
        if kind not in KINDS:
            return
        ts = self.clock()
        rec: dict[str, Any] = {"ts": round(ts, 3), "kind": kind, "instance": self.instance}
        rec.update({k: v for k, v in fields.items() if k in FIELDS and v is not None})
        day = datetime.fromtimestamp(ts, MSK).strftime("%Y-%m-%d")
        flush = False
        with self._lock:
            if day != self._day:
                if self._unsent:
                    flush = True  # дописать вчерашний файл до смены суток
                    self._flush_locked()
                self._day, self._events, self._unsent = day, [], 0
            self._events.append(json.dumps(rec, ensure_ascii=False))
            if len(self._events) > MAX_EVENTS:
                del self._events[: len(self._events) - MAX_EVENTS]
            self._unsent += 1
            flush = self._unsent >= BATCH
        if flush:
            self.flush()

    def start(self, version: str = "", provider: str = "") -> None:
        self.event("start", version=version, provider=provider, uptime_s=0)

    # ---- выгрузка ----
    def key(self) -> str:
        return f"{PREFIX}/{self._day}/{self.instance}.jsonl"

    def flush(self) -> bool:
        with self._lock:
            return self._flush_locked()

    def _flush_locked(self) -> bool:
        if not self._unsent or not self._day:
            return True
        body = ("\n".join(self._events) + "\n").encode("utf-8")
        try:
            self.put(self.key(), body)
        except Exception as exc:  # журнал не роняет сервис: события подождут
            log.warning("журнал стенда не записан в бакет (%s): %s событий подождут", type(exc).__name__, self._unsent)
            return False
        self._unsent = 0
        return True

    def run_background(self, period: float = FLUSH_S) -> None:
        def loop() -> None:
            while not self._stop.wait(period):
                self.event("step", step="uptime", uptime_s=int(self.clock() - self.started))
                self.flush()

        self._thread = threading.Thread(target=loop, name="stand-log", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self.flush()


def route_template(request: Any) -> str:
    """Маршрут без значений параметров: `/api/fleet/{vehicle_id}`, а не номер машины."""
    r = request.scope.get("route")
    path = getattr(r, "path", None)
    return str(path) if path else "-"


def from_env(instance: str | None = None) -> StandLog | None:
    """Стенд (задан S3_BUCKET): журнал в бакет по IAM-токену. `STAND_LOG=off` — выключить."""
    if not os.environ.get("S3_BUCKET", "").strip() or os.environ.get("STAND_LOG", "bucket") != "bucket":
        return None
    import httpx

    from service import kb_store
    from service.spend import RefreshingIamAuth

    http = httpx.Client()
    endpoint = os.environ.get("S3_ENDPOINT", kb_store.DEFAULT_ENDPOINT)
    bucket = kb_store.Bucket(os.environ["S3_BUCKET"].strip(), RefreshingIamAuth(http), http, endpoint)

    def put(key: str, data: bytes) -> None:
        bucket.put(key, data, "application/x-ndjson")

    return StandLog(put, instance=instance)
