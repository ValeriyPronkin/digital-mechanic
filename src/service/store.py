"""SQLite: журнал вызовов модели и инструментов (стоимость запроса) и память по ТС (B1).

Файл — `STATE_DB` (по умолчанию `.state/agent.db`, в git не входит). Цены — из окружения (₽ за 1 млн токенов),
по умолчанию — значения из `DEFAULT_PRICES` (проверить по действующему тарифу провайдера).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# ₽ за 1 млн токенов: (вход, выход). Это настройка: LLM_PRICE_IN_RUB / LLM_PRICE_OUT_RUB перекрывают.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "deepseek": (25.0, 100.0),
    "gigachat": (1500.0, 1500.0),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY, request_id TEXT, step INTEGER, provider TEXT, model TEXT,
    tokens_in INTEGER, tokens_out INTEGER, cost_rub REAL, ms INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY, request_id TEXT, step INTEGER, tool TEXT, args TEXT, ok INTEGER, ms INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS card_views (
    id INTEGER PRIMARY KEY, vehicle_id TEXT, session_id TEXT, status TEXT, fault_code TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS voice_calls (
    id INTEGER PRIMARY KEY, kind TEXT, units REAL, cost_rub REAL, ms INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY, ticket_id TEXT, vehicle_id TEXT, session_id TEXT, anomaly_type TEXT,
    urgency TEXT, body TEXT, ts REAL, fingerprint TEXT);
"""


def prices(provider: str) -> tuple[float, float]:
    base = DEFAULT_PRICES.get(provider, (0.0, 0.0))
    p_in = float(os.environ.get("LLM_PRICE_IN_RUB", base[0]))
    p_out = float(os.environ.get("LLM_PRICE_OUT_RUB", base[1]))
    return p_in, p_out


def cost_rub(provider: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = prices(provider)
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000


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
            cols = {r[1] for r in self._db.execute("PRAGMA table_info(tickets)")}
            if "fingerprint" not in cols:  # база от S2
                self._db.execute("ALTER TABLE tickets ADD COLUMN fingerprint TEXT")

    def _exec(self, sql: str, args: tuple[Any, ...] = ()) -> None:
        with self._lock:
            self._db.execute(sql, args)
            self._db.commit()

    def _rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    # ---- журнал ----
    def log_llm(
        self, request_id: str, step: int, provider: str, model: str, tokens_in: int, tokens_out: int, ms: int
    ) -> float:
        cost = cost_rub(provider, tokens_in, tokens_out)
        self._exec(
            "INSERT INTO llm_calls (request_id, step, provider, model, tokens_in, tokens_out, cost_rub, ms, ts)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (request_id, step, provider, model, tokens_in, tokens_out, cost, ms, time.time()),
        )
        return cost

    def log_tool(self, request_id: str, step: int, tool: str, args: dict[str, Any], ok: bool, ms: int) -> None:
        self._exec(
            "INSERT INTO tool_calls (request_id, step, tool, args, ok, ms, ts) VALUES (?,?,?,?,?,?,?)",
            (request_id, step, tool, json.dumps(args, ensure_ascii=False), int(ok), ms, time.time()),
        )

    def log_voice(self, kind: str, units: float, cost: float, ms: int) -> None:
        """Голос (#14): kind = stt (units — секунды записи) | tts (units — символы синтеза)."""
        self._exec(
            "INSERT INTO voice_calls (kind, units, cost_rub, ms, ts) VALUES (?,?,?,?,?)",
            (kind, units, cost, ms, time.time()),
        )

    def voice_spent_rub(self, since: float = 0.0) -> float:
        rows = self._rows("SELECT COALESCE(SUM(cost_rub), 0) AS s FROM voice_calls WHERE ts >= ?", (since,))
        return float(rows[0]["s"])

    def llm_calls(self, request_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM llm_calls WHERE request_id=? ORDER BY id", (request_id,))

    def spent_rub(self, since: float = 0.0) -> float:
        """Сумма ₽ по журналу; `since` — unix-время начала периода (0 — за всё время)."""
        rows = self._rows("SELECT COALESCE(SUM(cost_rub), 0) AS s FROM llm_calls WHERE ts >= ?", (since,))
        return float(rows[0]["s"])

    # ---- память по ТС ----
    def remember_view(self, vehicle_id: str, session_id: str, status: str, fault_code: str | None) -> None:
        self._exec(
            "INSERT INTO card_views (vehicle_id, session_id, status, fault_code, ts) VALUES (?,?,?,?,?)",
            (vehicle_id, session_id, status, fault_code, time.time()),
        )

    def ticket_for(self, fingerprint: str) -> str | None:
        rows = self._rows("SELECT ticket_id FROM tickets WHERE fingerprint=? LIMIT 1", (fingerprint,))
        return str(rows[0]["ticket_id"]) if rows else None

    def remember_ticket(self, ticket_id: str, body: dict[str, Any], fingerprint: str = "") -> None:
        self._exec(
            "INSERT INTO tickets (ticket_id, vehicle_id, session_id, anomaly_type, urgency, body, ts, fingerprint)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                ticket_id,
                body["vehicle_id"],
                body["session_id"],
                body["anomaly_type"],
                body["urgency"],
                json.dumps(body, ensure_ascii=False),
                time.time(),
                fingerprint,
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
