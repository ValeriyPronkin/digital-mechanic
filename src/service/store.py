"""SQLite: журнал вызовов модели и инструментов (стоимость запроса) и память по ТС (B1).

Файл — `STATE_DB` (по умолчанию `.state/agent.db`, в git не входит). Цены — `data/prices.json` (с источниками,
issue #16); окружение `LLM_PRICE_IN_RUB` / `LLM_PRICE_OUT_RUB` / `LLM_PRICE_CACHED_RUB` перекрывает
(₽ за 1 млн токенов).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

PRICES_PATH = Path(__file__).resolve().parents[2] / "data" / "prices.json"


@lru_cache(maxsize=1)
def price_table() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    return data


@dataclass(frozen=True)
class LLMPrice:
    """₽ за 1 млн токенов: вход без кэша, вход из кэша провайдера, выход."""

    tokens_in: float
    tokens_cached: float
    tokens_out: float


SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY, request_id TEXT, step INTEGER, provider TEXT, model TEXT,
    tokens_in INTEGER, tokens_out INTEGER, cost_rub REAL, ms INTEGER, ts REAL, tokens_cached INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY, request_id TEXT, step INTEGER, tool TEXT, args TEXT, ok INTEGER, ms INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS card_views (
    id INTEGER PRIMARY KEY, vehicle_id TEXT, session_id TEXT, status TEXT, fault_code TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY, ticket_id TEXT, vehicle_id TEXT, session_id TEXT, anomaly_type TEXT,
    urgency TEXT, body TEXT, ts REAL);
"""


def prices(provider: str) -> LLMPrice:
    t = price_table()
    row = t["llm"].get(provider) or {}
    if "rub" in row:
        base = row["rub"]
    elif "usd" in row:
        rate = float(t["usd_rub"]["value"])
        base = {k: float(v) * rate for k, v in row["usd"].items()}
    else:
        base = {"in": 0.0, "in_cached": 0.0, "out": 0.0}
    p_in = float(os.environ.get("LLM_PRICE_IN_RUB", base["in"]))
    p_cached = float(os.environ.get("LLM_PRICE_CACHED_RUB", base.get("in_cached", p_in)))
    p_out = float(os.environ.get("LLM_PRICE_OUT_RUB", base["out"]))
    return LLMPrice(p_in, p_cached, p_out)


def cost_rub(provider: str, tokens_in: int, tokens_out: int, tokens_cached: int = 0) -> float:
    """tokens_in — весь вход, из него tokens_cached попали в кэш провайдера и стоят дешевле."""
    p = prices(provider)
    cached = min(tokens_cached, tokens_in)
    return ((tokens_in - cached) * p.tokens_in + cached * p.tokens_cached + tokens_out * p.tokens_out) / 1_000_000


class Store:
    def __init__(self, path: Path | str | None = None) -> None:
        path = path or os.environ.get("STATE_DB", ".state/agent.db")
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            cols = {r[1] for r in self._db.execute("PRAGMA table_info(llm_calls)")}
            if "tokens_cached" not in cols:  # журнал из S2 — без колонки кэша
                self._db.execute("ALTER TABLE llm_calls ADD COLUMN tokens_cached INTEGER DEFAULT 0")
                self._db.commit()

    def _exec(self, sql: str, args: tuple[Any, ...] = ()) -> None:
        with self._lock:
            self._db.execute(sql, args)
            self._db.commit()

    def _rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    # ---- журнал ----
    def log_llm(
        self,
        request_id: str,
        step: int,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        ms: int,
        tokens_cached: int = 0,
    ) -> float:
        cost = cost_rub(provider, tokens_in, tokens_out, tokens_cached)
        self._exec(
            "INSERT INTO llm_calls (request_id, step, provider, model, tokens_in, tokens_out, cost_rub, ms, ts,"
            " tokens_cached) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (request_id, step, provider, model, tokens_in, tokens_out, cost, ms, time.time(), tokens_cached),
        )
        return cost

    def log_tool(self, request_id: str, step: int, tool: str, args: dict[str, Any], ok: bool, ms: int) -> None:
        self._exec(
            "INSERT INTO tool_calls (request_id, step, tool, args, ok, ms, ts) VALUES (?,?,?,?,?,?,?)",
            (request_id, step, tool, json.dumps(args, ensure_ascii=False), int(ok), ms, time.time()),
        )

    def llm_calls(self, request_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM llm_calls WHERE request_id=? ORDER BY id", (request_id,))

    def spent_rub(self) -> float:
        rows = self._rows("SELECT COALESCE(SUM(cost_rub), 0) AS s FROM llm_calls")
        return float(rows[0]["s"])

    # ---- память по ТС ----
    def remember_view(self, vehicle_id: str, session_id: str, status: str, fault_code: str | None) -> None:
        self._exec(
            "INSERT INTO card_views (vehicle_id, session_id, status, fault_code, ts) VALUES (?,?,?,?,?)",
            (vehicle_id, session_id, status, fault_code, time.time()),
        )

    def remember_ticket(self, ticket_id: str, body: dict[str, Any]) -> None:
        self._exec(
            "INSERT INTO tickets (ticket_id, vehicle_id, session_id, anomaly_type, urgency, body, ts)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                ticket_id,
                body["vehicle_id"],
                body["session_id"],
                body["anomaly_type"],
                body["urgency"],
                json.dumps(body, ensure_ascii=False),
                time.time(),
            ),
        )

    def vehicle_memory(self, vehicle_id: str, limit: int = 10) -> dict[str, list[dict[str, Any]]]:
        views = self._rows(
            "SELECT session_id, status, fault_code, ts FROM card_views WHERE vehicle_id=? ORDER BY id DESC LIMIT ?",
            (vehicle_id, limit),
        )
        tickets = self._rows(
            "SELECT ticket_id, session_id, anomaly_type, urgency, ts FROM tickets WHERE vehicle_id=?"
            " ORDER BY id DESC LIMIT ?",
            (vehicle_id, limit),
        )
        return {"viewed_cards": views, "tickets": tickets}
