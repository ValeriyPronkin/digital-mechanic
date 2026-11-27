"""Долгая сессия и запись для рекламации (встреча с заказчиком 27.11): механик возвращается через час или через полгода.

Что хранится (на стенде — в бакете при `V2_STATE_BUCKET=1`, по IAM; локально и в тестах — в памяти):
  v2/vehicles/<машина>/threads.json  — история обращений по машине: дата, проверка, тема, статус (условная запись
                                       с ETag и повтором — экземпляров несколько);
  v2/threads/by-id/<нить>.json       — нить целиком (состояние агента + стенограмма): продолжить с любого телефона;
  v2/records/<машина>/<нить>/<NNNNNN>.json — запись для рекламации, **только добавление**: объект создаётся условной
                                       записью `If-None-Match: *` и не перезаписывается; в каждой — хэш предыдущей,
                                       так что пропуск или правка видны при выгрузке (`verify`).
Запись: вопрос (ПДн замаскированы), ответ, страницы с цитатами, модель, версия индекса, коммит, время, уровень, язык.
Срок хранения — `CASE_RETENTION_DAYS` (по умолчанию 1095 дней): старше — не показывается и не выгружается; удаление из
бакета — правилом жизненного цикла на префиксы `v2/records/` и `v2/threads/` (настройка бакета, не код).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

log = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 1095
MAX_TRIES = 20


class Backend(Protocol):
    def read(self, key: str) -> tuple[bytes | None, str | None]: ...  # (данные, ETag); нет объекта — (None, None)
    def create(self, key: str, data: bytes) -> bool: ...  # только если объекта нет; есть — False
    def replace(self, key: str, data: bytes, etag: str) -> bool: ...  # только если ETag тот же; иначе — False
    def put(self, key: str, data: bytes) -> None: ...  # без условия (нить целиком — последняя версия)


class MemoryBackend:
    """Те же правила, что у бакета: create не перезаписывает, replace — только по ETag."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _etag(data: bytes) -> str:
        return hashlib.md5(data).hexdigest()  # noqa: S324 — как ETag S3, не для защиты

    def read(self, key: str) -> tuple[bytes | None, str | None]:
        with self._lock:
            data = self.objects.get(key)
        return (data, self._etag(data)) if data is not None else (None, None)

    def create(self, key: str, data: bytes) -> bool:
        with self._lock:
            if key in self.objects:
                return False
            self.objects[key] = data
            return True

    def replace(self, key: str, data: bytes, etag: str) -> bool:
        with self._lock:
            cur = self.objects.get(key)
            if cur is None or self._etag(cur) != etag:
                return False
            self.objects[key] = data
            return True

    def put(self, key: str, data: bytes) -> None:
        with self._lock:
            self.objects[key] = data


class BucketBackend:
    """Бакет через `kb_store.Bucket` (IAM-токен стенда); условная запись — как у счётчика расходов (D-23)."""

    def __init__(self, bucket: Any) -> None:
        self.bucket = bucket

    def _obj(self, key: str) -> Any:
        from service.spend import BucketObject

        return BucketObject(self.bucket, key)

    def read(self, key: str) -> tuple[bytes | None, str | None]:
        data, etag = self._obj(key).read()
        return data, etag

    def create(self, key: str, data: bytes) -> bool:
        return self._status(self._obj(key).write(data, None))

    def replace(self, key: str, data: bytes, etag: str) -> bool:
        return self._status(self._obj(key).write(data, etag))

    @staticmethod
    def _status(code: int) -> bool:
        if code in (200, 201):
            return True
        if code in (409, 412):
            return False
        raise RuntimeError(f"бакет ответил HTTP {code}")

    def put(self, key: str, data: bytes) -> None:
        self.bucket.put(key, data, "application/json")


def _dump(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")


def record_hash(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "sha256"}
    return hashlib.sha256(_dump(body)).hexdigest()


def verify(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Цепочка записей цела: номера подряд с 1, хэш каждой сходится, `prev_sha256` — хэш предыдущей."""
    prev = ""
    for i, r in enumerate(records, 1):
        if r.get("seq") != i:
            return False, f"запись №{i} отсутствует (дальше — №{r.get('seq')})"
        if r.get("sha256") != record_hash(r):
            return False, f"запись №{i} изменена после записи (хэш не сходится)"
        if r.get("prev_sha256", "") != prev:
            return False, f"запись №{i} не продолжает №{i - 1}"
        prev = r["sha256"]
    return True, f"цепочка цела: записей {len(records)}"


def now_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


class CaseLog:
    def __init__(
        self,
        backend: Backend | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.backend: Backend = backend or MemoryBackend()
        self.retention_days, self.clock = retention_days, clock

    @classmethod
    def from_env(cls) -> CaseLog:
        days = int(os.environ.get("CASE_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
        if os.environ.get("V2_STATE_BUCKET", "") != "1" or not os.environ.get("S3_BUCKET", "").strip():
            return cls(retention_days=days)
        import httpx

        from service import kb_store
        from service.spend import RefreshingIamAuth

        http = httpx.Client(timeout=10)
        endpoint = os.environ.get("S3_ENDPOINT", kb_store.DEFAULT_ENDPOINT)
        bucket = kb_store.Bucket(os.environ["S3_BUCKET"].strip(), RefreshingIamAuth(http), http, endpoint)
        return cls(BucketBackend(bucket), retention_days=days)

    # ---- срок хранения ----
    def expired(self, iso: str | None) -> bool:
        if not iso:
            return False
        age = self.clock() - datetime.fromisoformat(iso).timestamp()
        return age > self.retention_days * 86400

    # ---- нить целиком (продолжить с любого телефона) ----
    @staticmethod
    def _thread_key(thread_id: str) -> str:
        return f"v2/threads/by-id/{thread_id}.json"

    def save_thread(self, thread_id: str, data: dict[str, Any]) -> None:
        self.backend.put(self._thread_key(thread_id), _dump(data))

    def load_thread(self, thread_id: str) -> dict[str, Any] | None:
        raw, _ = self.backend.read(self._thread_key(thread_id))
        return json.loads(raw) if raw else None

    # ---- история обращений по машине ----
    @staticmethod
    def _index_key(vehicle_id: str) -> str:
        return f"v2/vehicles/{vehicle_id}/threads.json"

    def touch(self, vehicle_id: str, thread_id: str, **fields: Any) -> dict[str, Any]:
        """Обновить строку нити в истории машины (условная запись с повтором: экземпляров несколько)."""
        key = self._index_key(vehicle_id)
        for _ in range(MAX_TRIES):
            raw, etag = self.backend.read(key)
            index: dict[str, Any] = json.loads(raw) if raw else {"vehicle_id": vehicle_id, "threads": {}}
            row = index["threads"].get(thread_id) or {"thread_id": thread_id, "started_at": now_iso(self.clock())}
            row.update({k: v for k, v in fields.items() if v is not None})
            row["updated_at"] = now_iso(self.clock())
            index["threads"][thread_id] = row
            ok = self.backend.replace(key, _dump(index), etag) if etag else self.backend.create(key, _dump(index))
            if ok:
                return dict(row)
        raise RuntimeError(f"история {vehicle_id}: не удалось записать за {MAX_TRIES} попыток")

    def threads(self, vehicle_id: str) -> list[dict[str, Any]]:
        raw, _ = self.backend.read(self._index_key(vehicle_id))
        rows = list((json.loads(raw) if raw else {"threads": {}})["threads"].values())
        rows = [r for r in rows if not self.expired(r.get("updated_at"))]
        return sorted(rows, key=lambda r: r.get("updated_at", ""), reverse=True)

    def thread_row(self, vehicle_id: str, thread_id: str) -> dict[str, Any] | None:
        return next((r for r in self.threads(vehicle_id) if r["thread_id"] == thread_id), None)

    # ---- запись для рекламации: только добавление ----
    @staticmethod
    def _record_key(vehicle_id: str, thread_id: str, seq: int) -> str:
        return f"v2/records/{vehicle_id}/{thread_id}/{seq:06d}.json"

    def append(self, vehicle_id: str, thread_id: str, record: dict[str, Any], start: int = 1) -> dict[str, Any]:
        """Следующая запись цепочки. Объект создаётся только если его нет: занят другим экземпляром — следующий номер.
        `start` — с какого номера искать (число записей в истории + 1), чтобы не перечитывать всю цепочку."""
        seq = max(1, start)
        while True:  # первый свободный номер: перед ним все заняты
            raw, _ = self.backend.read(self._record_key(vehicle_id, thread_id, seq))
            if raw is None:
                break
            seq += 1
        for _ in range(MAX_TRIES):
            prev = ""
            if seq > 1:
                raw, _ = self.backend.read(self._record_key(vehicle_id, thread_id, seq - 1))
                prev = json.loads(raw)["sha256"] if raw else ""
            rec = {**record, "seq": seq, "thread_id": thread_id, "vehicle_id": vehicle_id, "prev_sha256": prev}
            rec.setdefault("at", now_iso(self.clock()))
            rec["sha256"] = record_hash(rec)
            if self.backend.create(self._record_key(vehicle_id, thread_id, seq), _dump(rec)):
                self.touch(vehicle_id, thread_id, records=seq)  # сколько записей должно быть: пропуск виден
                return rec
            seq += 1
        raise RuntimeError(f"запись {vehicle_id}/{thread_id}: не удалось добавить за {MAX_TRIES} попыток")

    def records(self, vehicle_id: str, thread_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seq = 1
        while True:
            raw, _ = self.backend.read(self._record_key(vehicle_id, thread_id, seq))
            if raw is None:
                return out
            out.append(json.loads(raw))
            seq += 1
