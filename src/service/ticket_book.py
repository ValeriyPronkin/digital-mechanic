"""Отправленные заявки — общие для всех экземпляров стенда (аудит 27.11, A2).

У каждого экземпляра своя SQLite (`STATE_DB=/tmp/agent.db`): заявку, отправленную через один экземпляр, другой
не видел — список заявок машины, карточка, реестр главного механика и «заявка создана» в парке приходили пустыми.
На стенде (задан `S3_BUCKET`) записи заявок лежат в одном объекте бакета `v2/sent-tickets.json`: запись — та же
строка, что в таблице `tickets` (номер ТОиР, тело, приоритет предложенный, строки со страницами, исход
дефектовки), изменение — чтение с ETag и условная запись с повтором, как у общего счётчика расходов (#11).

`id` записи — число из отпечатка заявки, одно на всех экземплярах: по нему интерфейс отмечает исход дефектовки.
Бакет недоступен — `Store` читает и пишет свою SQLite, как раньше (предупреждение в журнале).
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Any

from service.spend import CONFLICT, ConditionalStore

log = logging.getLogger(__name__)

KEY = "v2/sent-tickets.json"
MAX_ATTEMPTS = 8


def stable_id(fingerprint: str, ticket_id: str) -> int:
    """Номер записи для интерфейса: одинаковый на всех экземплярах; 48 бит — целое без потерь в JavaScript."""
    return int(hashlib.sha256((fingerprint or ticket_id).encode()).hexdigest()[:12], 16)


class SharedTickets:
    def __init__(self, obj: ConditionalStore, sleep: Callable[[float], None] = time.sleep) -> None:
        self.obj, self.sleep = obj, sleep
        self._lock = threading.Lock()

    def all(self) -> list[dict[str, Any]]:
        """Все записи, новые сверху. Ошибка бакета — исключение: решает вызывающий (`Store`)."""
        raw, _ = self.obj.read()
        rows = list(json.loads(raw).get("tickets") or []) if raw else []
        return sorted(rows, key=lambda r: (r.get("ts") or 0, r["id"]), reverse=True)

    def change(self, fn: Callable[[list[dict[str, Any]]], bool]) -> None:
        """`fn` меняет список записей на месте и говорит, менял ли он что-нибудь; запись — условная, с повтором."""
        with self._lock:
            for attempt in range(MAX_ATTEMPTS):
                raw, etag = self.obj.read()
                rows = list(json.loads(raw).get("tickets") or []) if raw else []
                if not fn(rows):
                    return
                data = json.dumps({"tickets": rows}, ensure_ascii=False).encode()
                status = self.obj.write(data, etag)
                if status in (200, 201, 204):
                    return
                if status not in CONFLICT:
                    raise RuntimeError(f"запись заявок в бакет: HTTP {status}")
                self.sleep(random.uniform(0.02, 0.1) * (attempt + 1))  # noqa: S311  # разнести повторы
            raise RuntimeError(f"запись заявок в бакет: {MAX_ATTEMPTS} конфликтов подряд")

    def add(self, row: dict[str, Any]) -> None:
        def put(rows: list[dict[str, Any]]) -> bool:
            if any(r["id"] == row["id"] for r in rows):  # та же заявка (отпечаток) уже записана другим экземпляром
                return False
            rows.append(row)
            return True

        self.change(put)

    def update(self, match: Callable[[dict[str, Any]], bool], **fields: Any) -> None:
        def set_fields(rows: list[dict[str, Any]]) -> bool:
            hit = [r for r in rows if match(r)]
            for r in hit:
                r.update(fields)
            return bool(hit)

        self.change(set_fields)
