"""Ограничение частоты запросов к модели: на клиента (IP) и на экземпляр в целом, скользящее окно 60 с.

Стенд публичный — без лимита ключи модели сожгут. Счётчики в памяти экземпляра: при нескольких экземплярах
общий предел умножается на их число; общий потолок расходов держит лимит ₽ (D-4, D-7) и баланс провайдера.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

WINDOW = 60.0


class RateLimiter:
    def __init__(self, per_client: int, total: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_client = per_client
        self.total = total
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> RateLimiter:
        return cls(
            per_client=int(os.environ.get("CHAT_RATE_PER_MIN", "10")),
            total=int(os.environ.get("CHAT_RATE_TOTAL_PER_MIN", "60")),
        )

    def check(self, client: str) -> float:
        """0 — можно; иначе сколько секунд подождать. Отказ не расходует квоту."""
        now = self.clock()
        with self._lock:
            q = self._hits.setdefault(client, deque())
            for d in (q, self._all):
                while d and now - d[0] >= WINDOW:
                    d.popleft()
            if len(q) >= self.per_client:
                return WINDOW - (now - q[0])
            if len(self._all) >= self.total:
                return WINDOW - (now - self._all[0])
            q.append(now)
            self._all.append(now)
            if len(self._hits) > 10_000:  # не копить память на ботах
                self._hits = {k: v for k, v in self._hits.items() if v}
            return 0.0


def client_key(request: Request) -> str:
    """IP клиента. За прокси Yandex Cloud — последний адрес X-Forwarded-For (его дописал прокси, не клиент)."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
