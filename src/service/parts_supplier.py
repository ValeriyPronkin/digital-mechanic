"""Поставщики запчастей — универсальный интерфейс; каждый поставщик — свой файл настроек (заказчик, 26–27.11).

Закупки у заказчика не формализованы: поставщик подключается при заключении договора файлом настроек, без программиста.
  PARTS_SUPPLIERS=<папка> или <файл1.json>,<файл2.json> — несколько поставщиков (D-N «Несколько поставщиков»):
      у каждого файла `kind` csv|http, `supplier` — имя, `fields` — сопоставление полей, `timeout_s`;
      секреты — только `env:ИМЯ_ПЕРЕМЕННОЙ` (значение — в .env / секретах стенда, не в файле).
      Опрос всех параллельно, таймаут — на каждого: упавший или медленный помечается «не ответил», остальные — в ответе.
  PARTS_SUPPLIER=none|csv|http (+ PARTS_SUPPLIER_CONFIG) — прежний способ, один поставщик; работает как раньше.
  Ничего не задано (по умолчанию, и на стенде) — каталог не подключён, честно так и говорим (STUB: parts-catalog).
find(обозначение или наименование) → предложения: поставщик, обозначение, наличие, цена, срок, ссылка — поля
необязательные; сортировка — в наличии, затем срок, затем цена.
Обозначения для поиска — только из руководства (D-29): `offers_for_parts` берёт обозначение из матрицы, а строку без
него ищет по названию с пометкой «по названию, проверьте».
Демо: data/demo/suppliers/ — два ВЫМЫШЛЕННЫХ поставщика (прайс-файл и HTTP-заглушка `make parts-demo`).
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_CONFIG = ROOT / "data" / "demo" / "parts_supplier_csv.json"
FIELDS = ("name", "designation", "available", "price_rub", "lead_days", "url")
NOT_CONNECTED = (
    "Каталог поставщика не подключён: данных о наличии, цене и сроке нет. Подключение — файлом настроек поставщика "
    "(PARTS_SUPPLIERS, csv или http) без изменения кода; путь внедрения — учётная система заказчика (например, 1С)."
)
BY_NAME = "по названию, проверьте"
DEFAULT_TIMEOUT_S = 5.0


@dataclass
class Offer:
    name: str | None = None
    designation: str | None = None
    available: str | None = None  # как у поставщика: «есть», «3 шт.», «под заказ»
    price_rub: float | None = None
    lead_days: int | None = None
    url: str | None = None
    supplier: str | None = None

    @property
    def in_stock(self) -> bool | None:
        """По строке наличия поставщика: «есть», «12 шт.» — да; «нет», «под заказ», «0» — нет; пусто — неизвестно."""
        a = (self.available or "").strip().casefold()
        if not a:
            return None
        if a.startswith(("нет", "под заказ", "ожида", "0")) or re.fullmatch(r"0+([.,]0+)?\s*(шт\.?)?", a):
            return False
        return True


def offer_view(o: Offer) -> dict[str, Any]:
    return {**asdict(o), "in_stock": o.in_stock}


def sort_key(o: Offer) -> tuple[int, float, float]:
    """В наличии → неизвестно → нет/под заказ; затем срок; затем цена (пустое — в конец)."""
    stock = {True: 0, None: 1, False: 2}[o.in_stock]
    return (stock, float("inf") if o.lead_days is None else o.lead_days, o.price_rub or float("inf"))


@dataclass
class SupplierStatus:
    name: str
    status: str  # ok — есть предложения; empty — позиции нет; failed — не ответил (ошибка или таймаут)
    note: str = ""


@dataclass
class Lookup:
    connected: bool
    note: str = ""
    offers: list[Offer] = field(default_factory=list)
    suppliers: list[SupplierStatus] = field(default_factory=list)
    failed: bool = False  # поставщик не ответил (а не «позиции нет»)

    def public(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "note": self.note,
            "offers": [offer_view(o) for o in self.offers],
            "suppliers": [asdict(s) for s in self.suppliers],
        }


class PartsSupplier(Protocol):
    def find(self, query: str) -> Lookup: ...


def _env_secret(value: str) -> str:
    """`env:ИМЯ` — значение переменной окружения; секреты в файле настроек не храним."""
    return os.environ.get(value.removeprefix("env:"), "") if value.startswith("env:") else value


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
        self.url = _env_secret(str(cfg["url"]))  # шаблон с {query}; адрес с ключом — тоже через env:
        self.items_key = str(cfg.get("items_key", ""))
        self.fields = dict(cfg["fields"])
        self.supplier = str(cfg.get("supplier", ""))
        self.headers = {k: _env_secret(str(v)) for k, v in (cfg.get("headers") or {}).items()}
        self.client = client or httpx.Client(timeout=float(cfg.get("timeout_s", DEFAULT_TIMEOUT_S)))

    def find(self, query: str) -> Lookup:
        try:
            resp = self.client.get(self.url.format(query=quote(query)), headers=self.headers)
            resp.raise_for_status()
            data: Any = resp.json()
        except (httpx.HTTPError, ValueError):
            return Lookup(
                connected=True, note=f"Поставщик «{self.supplier}» сейчас не ответил — повторите позже.", failed=True
            )
        for part in self.items_key.split(".") if self.items_key else []:
            data = data.get(part, []) if isinstance(data, dict) else []
        rows = data if isinstance(data, list) else []
        offers = [_offer(r, self.fields, self.supplier) for r in rows if isinstance(r, dict)]
        note = "" if offers else f"У поставщика «{self.supplier}» позиции нет."
        return Lookup(connected=True, note=note, offers=offers)


class SupplierSet:
    """Несколько поставщиков: опрос параллельно, таймаут на каждого; упавший или медленный — «не ответил»."""

    def __init__(self, suppliers: list[tuple[str, PartsSupplier, float]], workers: int = 8) -> None:
        self.suppliers = suppliers  # (имя, поставщик, таймаут, с)
        self.pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(suppliers))), thread_name_prefix="parts")

    def find(self, query: str) -> Lookup:
        started = time.monotonic()
        futures: list[tuple[str, float, Future[Lookup]]] = [
            (name, timeout, self.pool.submit(sup.find, query)) for name, sup, timeout in self.suppliers
        ]
        offers: list[Offer] = []
        statuses: list[SupplierStatus] = []
        for name, timeout, fut in futures:
            left = max(0.0, started + timeout - time.monotonic())  # общий старт: ждём не дольше таймаута каждого
            try:
                got = fut.result(timeout=left)
            except TimeoutError:
                fut.cancel()
                statuses.append(SupplierStatus(name, "failed", f"не ответил за {timeout:g} с"))
                continue
            except Exception as exc:  # поставщик не валит остальных
                statuses.append(SupplierStatus(name, "failed", f"не ответил ({type(exc).__name__})"))
                continue
            if got.failed:
                statuses.append(SupplierStatus(name, "failed", "не ответил"))
                continue
            for o in got.offers:
                o.supplier = o.supplier or name
            offers += got.offers
            statuses.append(SupplierStatus(name, "ok" if got.offers else "empty", "" if got.offers else "позиции нет"))
        offers.sort(key=sort_key)
        note = "" if offers else "Ни у одного подключённого поставщика позиции нет."
        if not offers and statuses and all(s.status == "failed" for s in statuses):
            note = "Поставщики сейчас не ответили — повторите позже."
        return Lookup(connected=True, note=note, offers=offers, suppliers=statuses)


def _resolve(path: Path | str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def supplier_from_config(
    cfg: dict[str, Any], kind: str | None = None, client: httpx.Client | None = None
) -> CsvSupplier | HttpSupplier:
    kind = (kind or str(cfg.get("kind", ""))).strip().lower()
    if kind == "csv":
        return CsvSupplier(
            _resolve(cfg["path"]), dict(cfg["fields"]), str(cfg.get("supplier", "")), str(cfg.get("delimiter", ";"))
        )
    if kind == "http":
        return HttpSupplier(cfg, client)
    raise ValueError(f"kind={kind!r}: ожидается csv или http")


def config_files(spec: str) -> list[Path]:
    """PARTS_SUPPLIERS: папка (все *.json по имени) или файлы через запятую."""
    files: list[Path] = []
    for part in (x.strip() for x in spec.split(",")):
        if not part:
            continue
        p = _resolve(part)
        files += sorted(p.glob("*.json")) if p.is_dir() else [p]
    return files


def from_env(client: httpx.Client | None = None) -> PartsSupplier:
    many = os.environ.get("PARTS_SUPPLIERS", "").strip()
    if many:
        suppliers: list[tuple[str, PartsSupplier, float]] = []
        for f in config_files(many):
            cfg = json.loads(f.read_text(encoding="utf-8"))
            if cfg.get("enabled", True) is False:
                continue
            name = str(cfg.get("supplier") or f.stem)
            suppliers.append(
                (name, supplier_from_config(cfg, client=client), float(cfg.get("timeout_s", DEFAULT_TIMEOUT_S)))
            )
        if not suppliers:
            raise ValueError(f"PARTS_SUPPLIERS={many}: ни одного файла поставщика")
        return SupplierSet(suppliers)
    kind = os.environ.get("PARTS_SUPPLIER", "none").strip().lower()
    if kind in ("", "none"):
        return NoSupplier()
    if kind not in ("csv", "http"):
        raise ValueError(f"PARTS_SUPPLIER={kind}: ожидается none, csv или http")
    cfg = json.loads(_resolve(os.environ.get("PARTS_SUPPLIER_CONFIG", "") or DEFAULT_CSV_CONFIG).read_text("utf-8"))
    return supplier_from_config(cfg, kind, client)


_LABEL_PAGE = re.compile(r",\s*стр\.\s*\d+\s*$")
_PAREN = re.compile(r"\s*\([^)]*\)")


def offers_for_parts(
    supplier: PartsSupplier, parts: list[str], designations: dict[str, str] | None = None
) -> dict[str, Any]:
    """Предложения по строкам запчастей черновика заявки (поле `parts_offers` в /api/v2).

    `designations` — строка заявки → обозначение **из руководства** (матрица, D-29). Строку без него ищем по названию
    (без страницы и без скобок — обозначение, написанное моделью, не используем) и помечаем «по названию, проверьте».
    """
    designations = designations or {}
    items: list[dict[str, Any]] = []
    connected = True
    note = ""
    for i, part in enumerate(parts):
        designation = designations.get(part)
        query = designation or _PAREN.sub("", _LABEL_PAGE.sub("", part)).strip()
        if not query:
            continue
        got = supplier.find(query)
        connected, note = got.connected, got.note if not got.connected else note
        if not got.connected:
            break
        items.append(
            {
                "index": i,
                "part": part,
                "query": query,
                "by": "designation" if designation else "name",
                "check": "" if designation else BY_NAME,
                "offers": [offer_view(o) for o in sorted(got.offers, key=sort_key)],
                "suppliers": [asdict(s) for s in got.suppliers],
                "note": got.note,
            }
        )
    return {"connected": connected, "note": note, "items": items if connected else []}
