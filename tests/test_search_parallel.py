"""Несколько запросов поиска — одновременно (замер стенда 27.11: 4 запроса подряд ≈0,3–0,45 с из-за эмбеддингов);
выдача та же, что при запросах по очереди."""

from __future__ import annotations

import threading
import time

from service.clients import MLClient, ToirClient
from service.manual_search import ManualHit
from test_agent import make_agent


class SlowSearch:
    """Каждый запрос ждёт 0,2 с, как запрос эмбеддинга; страницы — по номеру запроса."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.2)
        with self.lock:
            self.active -= 1
        n = int(query[1:])
        return [ManualHit("doc-1", "РК", n * 10 + r, f"{query}-{r}", "текст") for r in range(k)]


def test_queries_run_at_once_and_keep_the_order(ml: MLClient, toir: ToirClient) -> None:
    search = SlowSearch()
    ag, _ = make_agent([], ml, toir, search=search)
    t0 = time.monotonic()
    hits = ag._search_many(["q1", "q2", "q2", "", "q3", "q4"], "ЯМЗ-236М2", k=6)
    took = time.monotonic() - t0
    assert search.peak == 4 and took < 0.6  # по очереди было бы 0,8 с
    assert [h.pdf_page for h in hits] == [10, 20, 30, 40, 11, 21]  # по кругу: лучшие из каждого запроса


def test_one_query_without_threads(ml: MLClient, toir: ToirClient) -> None:
    search = SlowSearch()
    ag, _ = make_agent([], ml, toir, search=search)
    assert [h.pdf_page for h in ag._search_many(["q1", "q1"], "ЯМЗ-236М2", k=2)] == [10, 11]
    assert search.peak == 1
