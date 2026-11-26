"""Общий счётчик расходов на модель для всех экземпляров стенда (issue #11, D-13 → решено, D-17).

На стенде журнал SQLite у каждого экземпляра свой и обнуляется при холодном старте — лимит D-11 (100 ₽ в сутки по
Москве, 1 000 ₽ всего) нужно считать по общему счётчику. Он лежит в частном бакете рядом с индексом:

  spend/ledger.json  {"total_rub": …, "days": {"2026-11-26": …}, "updated": "…"}

Пишет стенд по IAM-токену своего сервисного аккаунта (статического ключа в контейнере нет). Одновременная запись
нескольких экземпляров — условной записью: прочитали с ETag → PUT с If-Match (первый раз — If-None-Match: *) →
конфликт (412/409) — перечитать и прибавить заново. Сумма не теряется: прибавка повторяется, пока не запишется.

Если бакет недоступен, расход не теряется: копится в экземпляре и уходит при следующей удачной записи; лимит
до этого проверяется по последнему прочитанному значению плюс накопленное.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

KEY = "spend/ledger.json"
MSK = timezone(timedelta(hours=3))
MAX_ATTEMPTS = 8
CONFLICT = (409, 412)  # 412 Precondition Failed; 409 OperationAborted — «конфликтующие условные операции»
KEEP_DAYS = 40  # дни старше — выбрасываются из файла (общая сумма остаётся в total_rub)


def moscow_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, MSK).strftime("%Y-%m-%d")


class SpendLedger(Protocol):
    def add(self, rub: float, ts: float) -> None: ...
    def spent_today(self, ts: float) -> float: ...
    def spent_total(self) -> float: ...


@dataclass
class Snapshot:
    total: float
    days: dict[str, float]
    etag: str | None  # None — объекта ещё нет


class ConditionalStore(Protocol):
    """GET с ETag и условный PUT. Возвращает HTTP-статус записи — конфликт решает счётчик."""

    def read(self) -> tuple[bytes | None, str | None]: ...
    def write(self, data: bytes, if_match: str | None) -> int: ...


class RefreshingIamAuth:
    """IAM-токен сервисного аккаунта из метаданных, обновляется раз в TOKEN_TTL: экземпляр живёт дольше токена
    (kb_store берёт токен один раз — ему хватает, он качает индекс только при старте)."""

    TOKEN_TTL = 30 * 60

    def __init__(self, http: httpx.Client, clock: Callable[[], float] = time.monotonic) -> None:
        self.http, self.clock = http, clock
        self._token, self._at = "", -1e9

    def __call__(self, method: str, url: str, headers: dict[str, str], payload_sha: str) -> dict[str, str]:
        from service.kb_store import metadata_token

        if not self._token or self.clock() - self._at > self.TOKEN_TTL:
            self._token, self._at = metadata_token(self.http), self.clock()
        return {**headers, "X-YaCloud-SubjectToken": self._token}


class BucketObject:
    """spend/ledger.json в бакете через `kb_store.Bucket` (авторизация — IAM-токен стенда)."""

    def __init__(self, bucket: Any, key: str = KEY) -> None:
        self.bucket, self.key = bucket, key

    def _url(self) -> str:
        from service.kb_store import object_url

        return object_url(self.bucket.endpoint, self.bucket.bucket, self.key)

    def read(self) -> tuple[bytes | None, str | None]:
        from service.kb_store import _sha256

        url = self._url()
        r = self.bucket.http.get(url, headers=self.bucket.auth("GET", url, {}, _sha256(b"")), timeout=10)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        return r.content, r.headers.get("ETag")

    def write(self, data: bytes, if_match: str | None) -> int:
        from service.kb_store import _sha256

        url = self._url()
        cond = {"If-Match": if_match} if if_match else {"If-None-Match": "*"}
        headers = self.bucket.auth("PUT", url, {"content-type": "application/json", **cond}, _sha256(data))
        r = self.bucket.http.put(url, content=data, headers=headers, timeout=10)
        return int(r.status_code)


class SharedLedger:
    """Счётчик в общем объекте с условной записью и повтором; при сбое бакета — копит у себя и не теряет."""

    def __init__(
        self,
        store: ConditionalStore,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store, self.clock, self.sleep = store, clock, sleep
        self._lock = threading.Lock()
        self._pending: dict[str, float] = {}  # не записано из-за сбоя бакета: день → ₽
        self._seen = Snapshot(0.0, {}, None)  # последнее прочитанное

    # ---- чтение ----
    def _read(self) -> Snapshot:
        raw, etag = self.store.read()
        if raw is None:
            return Snapshot(0.0, {}, None)
        data = json.loads(raw)
        return Snapshot(float(data.get("total_rub", 0.0)), {k: float(v) for k, v in data.get("days", {}).items()}, etag)

    def _refresh(self) -> Snapshot:
        try:
            snap = self._read()
        except (httpx.HTTPError, ValueError, OSError, RuntimeError) as exc:
            log.warning("счётчик расходов в бакете не прочитан: %s — считаю по последнему значению", exc)
            return self._seen
        self._seen = snap
        return snap

    def spent_total(self) -> float:
        with self._lock:
            return self._refresh().total + sum(self._pending.values())

    def spent_today(self, ts: float) -> float:
        day = moscow_day(ts)
        with self._lock:
            return self._refresh().days.get(day, 0.0) + self._pending.get(day, 0.0)

    # ---- запись ----
    def add(self, rub: float, ts: float) -> None:
        if rub <= 0:
            return
        with self._lock:
            day = moscow_day(ts)
            self._pending[day] = self._pending.get(day, 0.0) + rub
            self._flush()

    def _flush(self) -> None:
        """Прибавить накопленное к общему объекту: условная запись, при конфликте — перечитать и повторить."""
        for attempt in range(MAX_ATTEMPTS):
            try:
                snap = self._read()
            except (httpx.HTTPError, ValueError, OSError, RuntimeError) as exc:
                log.warning("счётчик расходов не прочитан (%s): %.4f ₽ подождут следующей записи", exc,
                            sum(self._pending.values()))  # fmt: skip
                return
            days = dict(snap.days)
            for d, v in self._pending.items():
                days[d] = round(days.get(d, 0.0) + v, 6)
            days_kept = {d: days[d] for d in sorted(days)[-KEEP_DAYS:]}
            body: dict[str, Any] = {
                "total_rub": round(snap.total + sum(self._pending.values()), 6),
                "days": days_kept,
                "updated": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            try:
                status = self.store.write(json.dumps(body, ensure_ascii=False).encode("utf-8"), snap.etag)
            except (httpx.HTTPError, OSError, RuntimeError) as exc:
                log.warning("счётчик расходов не записан (%s): сумма подождёт следующей записи", exc)
                return
            if status in (200, 201, 204):
                self._pending.clear()
                self._seen = Snapshot(float(body["total_rub"]), dict(days_kept), None)
                return
            if status in CONFLICT:
                self.sleep(random.uniform(0.02, 0.1) * (attempt + 1))  # noqa: S311  # разнести повторы
                continue
            log.warning("счётчик расходов: запись вернула HTTP %s — сумма подождёт следующей записи", status)
            return
        log.warning("счётчик расходов: %s конфликтов подряд — сумма подождёт следующей записи", MAX_ATTEMPTS)
