"""Одна заявка на одно подтверждение для всех экземпляров стенда (ревью 27.11).

У каждого экземпляра своя SQLite (`STATE_DB=/tmp/agent.db`): проверка «эта заявка уже отправлена» по ней
не видит, что заявку с тем же отпечатком отправил другой экземпляр. Поэтому до отправки в ТОиР — отметка
`v2/tickets/{отпечаток}.json` в общем бакете условной записью (`If-None-Match: *`): создать её может только один.

Отметка: `{"state": "sending"}` → после ответа ТОиР `{"state": "sent", "ticket_id", "status"}`; ТОиР не ответил —
`{"state": "failed"}`, и отметку можно взять снова. «sending» старше `STALE_S` (экземпляр упал между отметкой
и ответом ТОиР) тоже берётся снова. Бакет недоступен — работает прежняя проверка экземпляра, заявка не блокируется.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from service.spend import CONFLICT, ConditionalStore

log = logging.getLogger(__name__)

PREFIX = "v2/tickets/"
STALE_S = 120.0  # дольше любого ответа ТОиР (таймаут клиента) — отметку «sending» считаем брошенной


class Claim:
    """Итог попытки взять отметку: `mine` — отправляем мы; иначе `ticket_id` уже отправленной или None
    (отправляет другой экземпляр прямо сейчас)."""

    def __init__(self, mine: bool, ticket_id: str | None = None, status: str = "") -> None:
        self.mine, self.ticket_id, self.status = mine, ticket_id, status


class TicketMarks:
    def __init__(self, objects: Callable[[str], ConditionalStore], clock: Callable[[], float] = time.time) -> None:
        self.objects, self.clock = objects, clock

    def _obj(self, fingerprint: str) -> ConditionalStore:
        return self.objects(f"{PREFIX}{fingerprint}.json")

    def _body(self, **data: Any) -> bytes:
        return json.dumps({**data, "ts": self.clock()}, ensure_ascii=False).encode()

    def claim(self, fingerprint: str) -> Claim:
        obj = self._obj(fingerprint)
        try:
            for _ in range(3):
                code = obj.write(self._body(state="sending"), None)
                if code in (200, 201):
                    return Claim(True)
                if code not in CONFLICT:
                    raise RuntimeError(f"HTTP {code}")
                raw, etag = obj.read()
                if raw is None:
                    continue  # отметку сняли между записью и чтением — пробуем снова
                mark = json.loads(raw)
                if mark.get("ticket_id"):
                    return Claim(False, str(mark["ticket_id"]), str(mark.get("status") or ""))
                stale = self.clock() - float(mark.get("ts") or 0) > STALE_S
                if mark.get("state") == "failed" or stale:
                    if obj.write(self._body(state="sending"), etag) in (200, 201):
                        return Claim(True)
                    continue
                return Claim(False)
        except Exception as exc:  # бакет недоступен: не блокируем заявку, остаётся проверка экземпляра
            log.warning("отметка заявки в бакете не взята: %s — проверка только по экземпляру", exc)
            return Claim(True)
        return Claim(False)

    def sent(self, fingerprint: str, ticket_id: str, status: str) -> None:
        self._finish(fingerprint, self._body(state="sent", ticket_id=ticket_id, status=status))

    def failed(self, fingerprint: str) -> None:
        self._finish(fingerprint, self._body(state="failed"))

    def _finish(self, fingerprint: str, data: bytes) -> None:
        obj = self._obj(fingerprint)
        try:
            _, etag = obj.read()
            obj.write(data, etag)  # отметка наша: перезапись по своему ETag
        except Exception as exc:
            log.warning("отметка заявки в бакете не обновлена: %s", exc)
