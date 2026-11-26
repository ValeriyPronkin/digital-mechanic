"""Поставщик запчастей — универсальный интерфейс, реализация выбирается настройкой (заказчик, 26.11).

Закупки у заказчика не формализованы, договоров с поставщиками нет: подключение к поставщику — конфиг, а не код.
  PARTS_SUPPLIER=none (по умолчанию) — каталог не подключён, честно так и говорим (STUB: parts-catalog);
  PARTS_SUPPLIER=csv  — прайс-файл; поля сопоставляются файлом настроек PARTS_SUPPLIER_CONFIG;
  PARTS_SUPPLIER=http — HTTP API поставщика: шаблон адреса, ключ ответа со списком, сопоставление полей, заголовки
                         из переменных окружения (секреты — только в .env).
find(обозначение или наименование) → предложения: наличие, цена, срок, ссылка — все поля необязательные.
Пример: data/demo/parts_supplier_csv.json + data/demo/parts_prices_demo.csv (ВЫМЫШЛЕННЫЕ данные).
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_CONFIG = ROOT / "data" / "demo" / "parts_supplier_csv.json"
FIELDS = ("name", "designation", "available", "price_rub", "lead_days", "url")
NOT_CONNECTED = (
    "Каталог поставщика не подключён: данных о наличии, цене и сроке нет. Подключение — настройкой PARTS_SUPPLIER "
    "(csv или http) без изменения кода; путь внедрения — учётная система заказчика (например, 1С)."
)


@dataclass
class Offer:
    name: str | None = None
    designation: str | None = None
    available: str | None = None  # как у поставщика: «есть», «3 шт.», «под заказ»
    price_rub: float | None = None
    lead_days: int | None = None
    url: str | None = None
    supplier: str | None = None


@dataclass
class Lookup:
    connected: bool
    note: str = ""
    offers: list[Offer] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {"connected": self.connected, "note": self.note, "offers": [asdict(o) for o in self.offers]}


class PartsSupplier(Protocol):
    def find(self, query: str) -> Lookup: ...


def _key(text: str) -> str:
    return re.sub(r"[\s.\-–]", "", text).casefold()


def _offer(row: dict[str, Any], fields: dict[str, str], supplier: str) -> Offer:
    def get(name: str) -> Any:
        col = fields.get(name)
        value = row.get(col) if col else None
        return None if value in (None, "") else value

    def num(value: Any, kind: type) -> Any:
        try:
            return kind(str(value).replace(",", ".").replace(" ", "")) if value is not None else None
        except ValueError:
            return None

    return Offer(
        name=get("name"),
        designation=get("designation"),
        available=None if get("available") is None else str(get("available")),
        price_rub=num(get("price_rub"), float),
        lead_days=num(get("lead_days"), int),
        url=get("url"),
        supplier=supplier or None,
    )


def _match(offers: list[Offer], query: str) -> list[Offer]:
    """Сначала точное обозначение (без пробелов, точек и дефисов), иначе — наименование содержит запрос."""
    q = _key(query)
    exact = [o for o in offers if o.designation and _key(o.designation) == q]
    if exact:
        return exact
    words = query.casefold().split()
    return [o for o in offers if o.name and all(w in o.name.casefold() for w in words)]


class NoSupplier:
    """STUB: parts-catalog — поставщик не подключён: ни наличия, ни цены, ни срока не выдумываем."""

    def find(self, query: str) -> Lookup:
        return Lookup(connected=False, note=NOT_CONNECTED)


class CsvSupplier:
    def __init__(self, path: Path, fields: dict[str, str], supplier: str = "", delimiter: str = ";") -> None:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
        self.offers = [_offer(row, fields, supplier) for row in csv.DictReader(lines, delimiter=delimiter)]
        self.supplier = supplier

    def find(self, query: str) -> Lookup:
        found = _match(self.offers, query)
        note = "" if found else f"У поставщика «{self.supplier}» позиции нет."
        return Lookup(connected=True, note=note, offers=found)


class HttpSupplier:
    def __init__(self, cfg: dict[str, Any], client: httpx.Client | None = None) -> None:
        self.url = str(cfg["url"])  # шаблон с {query}
        self.items_key = str(cfg.get("items_key", ""))
        self.fields = dict(cfg["fields"])
        self.supplier = str(cfg.get("supplier", ""))
        self.headers = {k: os.environ.get(v.removeprefix("env:"), "") if v.startswith("env:") else v
                        for k, v in (cfg.get("headers") or {}).items()}  # fmt: skip
        self.client = client or httpx.Client(timeout=float(cfg.get("timeout_s", 10)))

    def find(self, query: str) -> Lookup:
        try:
            resp = self.client.get(self.url.format(query=quote(query)), headers=self.headers)
            resp.raise_for_status()
            data: Any = resp.json()
        except (httpx.HTTPError, ValueError):
            return Lookup(connected=True, note=f"Поставщик «{self.supplier}» сейчас не ответил — повторите позже.")
        for part in self.items_key.split(".") if self.items_key else []:
            data = data.get(part, []) if isinstance(data, dict) else []
        rows = data if isinstance(data, list) else []
        offers = [_offer(r, self.fields, self.supplier) for r in rows if isinstance(r, dict)]
        note = "" if offers else f"У поставщика «{self.supplier}» позиции нет."
        return Lookup(connected=True, note=note, offers=offers)


def from_env(client: httpx.Client | None = None) -> PartsSupplier:
    kind = os.environ.get("PARTS_SUPPLIER", "none").strip().lower()
    if kind in ("", "none"):
        return NoSupplier()
    path = Path(os.environ.get("PARTS_SUPPLIER_CONFIG", "") or DEFAULT_CSV_CONFIG)
    cfg = json.loads((path if path.is_absolute() else ROOT / path).read_text(encoding="utf-8"))
    if kind == "csv":
        csv_path = Path(cfg["path"])
        return CsvSupplier(
            csv_path if csv_path.is_absolute() else ROOT / csv_path,
            dict(cfg["fields"]),
            str(cfg.get("supplier", "")),
            str(cfg.get("delimiter", ";")),
        )
    if kind == "http":
        return HttpSupplier(cfg, client)
    raise ValueError(f"PARTS_SUPPLIER={kind}: ожидается none, csv или http")
