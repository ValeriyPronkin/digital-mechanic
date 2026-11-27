"""Сброс демо-машин перед повторным дублем видео (R3 демо-плана): после отправленной заявки «Создать заявку»
по этой проверке пропадает, а нить показывает прошлый дубль.

    make reset-demo ARGS=--dry-run                        # напечатать, что будет удалено; ничего не удаляет
    make reset-demo                                       # удалить по списку DEFAULT
    make reset-demo ARGS="--only B418HK98/S-0009"         # только эта проверка (машина без /S-… — все её проверки)

Удаляет только то, что относится к машинам и проверкам из списка:
- бакет `S3_BUCKET` (статический ключ `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` из `.env`, как `make logs` и
  `make kb-publish`; ключ не печатается): нити разговора интерфейса v2 `v2/threads/*.json`, у которых `session_id`
  из списка (номера проверок в парке уникальны), и отметки отправленных заявок `v2/tickets/{отпечаток}.json` (PR #104).
  Отпечаток — `agent.fingerprint` заявки из стенограммы этих нитей и из локальной SQLite; чужие отметки не трогаются;
- общая книга отправленных заявок стенда `v2/sent-tickets.json` (A2, `service.ticket_book`): строки этих
  проверок — условной записью с ETag, как пишет сам стенд. Без этого новая ревизия стенда снова видела заявку;
- локальная SQLite (`STATE_DB`, по умолчанию `.state/agent.db`): строки `tickets` и `card_views` этих проверок.

Чего скрипт сделать не может — печатает команду: у каждого экземпляра стенда своя SQLite (`STATE_DB=/tmp/agent.db`)
и копия нитей в памяти, а Mock ТОиР хранит заявки в памяти процесса. Это сбрасывает только новая ревизия
контейнеров (Actions → Stand → Run workflow). С `--stand URL` скрипт спрашивает стенд (только чтение), видит ли он
ещё заявки по этим проверкам, — тогда перезапуск нужен.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

ROOT = Path(__file__).resolve().parents[1]
VEHICLES = ROOT / "data" / "vehicles.json"
REPO = "ValeriyPronkin/digital-mechanic"
THREADS = "v2/threads/"
MARKS = "v2/tickets/"
# Сценарий видео и запасные машины для живых нажатий (демо-план 27.11): основная, запасная, сбой записи, затем
# A427 (класс 3), T792 (посторонний текст), C808 (турбина на карбюраторном), K961 (запись с помехами).
DEFAULT = (
    "B418HK98/S-0009",
    "M739BA198/S-0104",
    "H142OX78/S-0113",
    "A427MA78",
    "T792HO98",
    "C808CM178",
    "K961TH198",
)
RESTART = (
    f"gh workflow run stand.yml -R {REPO} --ref main -f min_instances=1\n"
    f"    gh run watch -R {REPO} $(gh run list -R {REPO} --workflow stand.yml --limit 1 "
    "--json databaseId -q '.[0].databaseId')"
)


class ResetError(RuntimeError):
    pass


# ---------- что сбрасываем ----------


@dataclass(frozen=True)
class Target:
    vehicle: str
    sessions: frozenset[str]

    def label(self) -> str:
        return f"{self.vehicle}/{','.join(sorted(self.sessions))}"


def load_fleet(path: Path = VEHICLES) -> dict[str, list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {v["vehicle_id"]: [s["session_id"] for s in v["sessions"]] for v in data["vehicles"]}


def parse_targets(specs: Iterable[str], fleet: dict[str, list[str]]) -> list[Target]:
    """`B418HK98/S-0009` — одна проверка; `A427MA78` — все проверки машины. Опечатка — ошибка, а не «ничего»."""
    out: list[Target] = []
    for spec in specs:
        vehicle, _, session = spec.strip().partition("/")
        if vehicle not in fleet:
            raise ResetError(f"машины {vehicle!r} нет в data/vehicles.json")
        if session and session not in fleet[vehicle]:
            raise ResetError(f"у {vehicle} нет проверки {session!r} (есть: {', '.join(fleet[vehicle])})")
        out.append(Target(vehicle, frozenset([session] if session else fleet[vehicle])))
    return out


def session_owner(targets: list[Target]) -> dict[str, str]:
    return {s: t.vehicle for t in targets for s in t.sessions}


# ---------- хранилища ----------


class Objects(Protocol):
    def keys(self, prefix: str) -> list[str]: ...
    def get(self, key: str) -> bytes | None: ...  # None — объекта нет
    def delete(self, key: str) -> None: ...


class S3Objects:
    """Бакет стенда по статическому ключу (SigV4, `kb_store`), как `make logs`; DELETE — здесь же."""

    def __init__(self, bucket: Any) -> None:
        self.bucket = bucket

    @classmethod
    def from_env(cls, http: httpx.Client) -> S3Objects:
        from service import kb_store

        name = os.environ.get("S3_BUCKET", "").strip()
        key_id, secret = os.environ.get("S3_ACCESS_KEY_ID", ""), os.environ.get("S3_SECRET_ACCESS_KEY", "")
        if not (key_id and secret):
            raise ResetError("для бакета нужны S3_ACCESS_KEY_ID и S3_SECRET_ACCESS_KEY (статический ключ из .env)")
        endpoint = os.environ.get("S3_ENDPOINT", kb_store.DEFAULT_ENDPOINT)
        return cls(kb_store.Bucket(name, kb_store.sigv4_auth(key_id, secret), http, endpoint))

    def keys(self, prefix: str) -> list[str]:
        from stand_logs import list_keys

        return list_keys(self.bucket, prefix)

    def _call(self, method: str, key: str) -> httpx.Response:
        from service.kb_store import _sha256, object_url

        url = object_url(self.bucket.endpoint, self.bucket.bucket, key)
        headers = self.bucket.auth(method, url, {}, _sha256(b""))
        return self.bucket.http.request(method, url, headers=headers, timeout=30)  # type: ignore[no-any-return]

    def get(self, key: str) -> bytes | None:
        r = self._call("GET", key)
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise ResetError(f"GET {key}: HTTP {r.status_code}")
        return r.content

    def delete(self, key: str) -> None:
        r = self._call("DELETE", key)
        if r.status_code not in (200, 204, 404):
            raise ResetError(f"DELETE {key}: HTTP {r.status_code}")


# ---------- план ----------


@dataclass(frozen=True)
class Row:
    table: str  # tickets | card_views
    pk: int
    vehicle: str
    session: str
    what: str  # номер заявки или статус карточки
    fingerprint: str = ""


@dataclass
class Plan:
    threads: list[tuple[str, str, str, int]] = field(default_factory=list)  # ключ, машина, проверка, реплик
    marks: list[tuple[str, str, str, str]] = field(default_factory=list)  # ключ, машина, проверка, что в отметке
    rows: list[Row] = field(default_factory=list)
    other_threads: int = 0
    other_marks: list[str] = field(default_factory=list)  # отметки, которые не удалось связать с машинами списка
    unreadable: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.threads or self.marks or self.rows)


def ticket_fingerprint(payload: dict[str, Any]) -> str | None:
    """Ключ отметки #104: тот же `agent.fingerprint` от тела заявки, что ушло в ТОиР."""
    from service.agent import fingerprint
    from service.clients import TicketRequest

    try:
        return fingerprint(TicketRequest.model_validate(payload))
    except ValueError:
        return None


def thread_fingerprints(data: dict[str, Any]) -> dict[str, str]:
    """Отпечаток → номер заявки (или «черновик») из стенограммы нити."""
    out: dict[str, str] = {}
    for turn in data.get("transcript") or []:
        ticket = turn.get("ticket") if isinstance(turn, dict) and turn.get("role") == "ticket" else None
        if isinstance(ticket, dict) and isinstance(ticket.get("payload"), dict):
            fp = ticket_fingerprint(ticket["payload"])
            if fp:
                out[fp] = str(ticket.get("ticket_id") or "")
    pending = data.get("pending")
    if isinstance(pending, dict) and isinstance(pending.get("pending_id"), str):
        out.setdefault(pending["pending_id"], "черновик")  # «Отправить» мог не дойти до ТОиР — отметка «failed»
    return out


def db_rows(db: sqlite3.Connection, owner: dict[str, str]) -> list[Row]:
    rows: list[Row] = []
    have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    marks = "?," * (len(owner) - 1) + "?"
    if "tickets" in have:
        cols = {r[1] for r in db.execute("PRAGMA table_info(tickets)")}
        fp = "fingerprint" if "fingerprint" in cols else "''"
        sql = f"SELECT id, vehicle_id, session_id, ticket_id, {fp} FROM tickets WHERE session_id IN ({marks})"  # noqa: S608
        for pk, vid, sid, tid, f in db.execute(sql, tuple(owner)):
            if owner.get(sid) == vid:
                rows.append(Row("tickets", int(pk), vid, sid, str(tid), str(f or "")))
    if "card_views" in have:
        sql = f"SELECT id, vehicle_id, session_id, status FROM card_views WHERE session_id IN ({marks})"  # noqa: S608
        for pk, vid, sid, status in db.execute(sql, tuple(owner)):
            if owner.get(sid) == vid:
                rows.append(Row("card_views", int(pk), vid, sid, str(status)))
    return rows


def make_plan(objects: Objects | None, db: sqlite3.Connection | None, targets: list[Target]) -> Plan:
    owner = session_owner(targets)
    plan = Plan()
    fps: dict[str, tuple[str, str, str]] = {}  # отпечаток → машина, проверка, номер
    if db is not None:
        plan.rows = db_rows(db, owner)
        for row in plan.rows:
            if row.fingerprint:
                fps[row.fingerprint] = (row.vehicle, row.session, row.what)
    if objects is None:
        return plan
    keys = [k for k in objects.keys(THREADS) if k.endswith(".json")]
    with ThreadPoolExecutor(8) as pool:
        bodies = list(pool.map(objects.get, keys))
    for key, raw in zip(keys, bodies, strict=True):
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            plan.unreadable.append(key)
            continue
        sid = data.get("session_id") if isinstance(data, dict) else None
        if sid not in owner:
            plan.other_threads += 1
            continue
        vid = owner[sid]
        plan.threads.append((key, vid, sid, len(data.get("transcript") or [])))
        for fp, tid in thread_fingerprints(data).items():
            fps.setdefault(fp, (vid, sid, tid))
    found = set(objects.keys(MARKS))
    for fp, (vid, sid, tid) in sorted(fps.items()):
        key = f"{MARKS}{fp}.json"
        if key not in found:
            continue
        raw = objects.get(key)
        mark = json.loads(raw) if raw else {}
        what = f"{mark.get('state', '?')} {mark.get('ticket_id') or tid}".strip()
        plan.marks.append((key, vid, sid, what))
    mine = {m[0] for m in plan.marks}
    plan.other_marks = sorted(k for k in found if k not in mine)
    return plan


def apply(plan: Plan, objects: Objects | None, db: sqlite3.Connection | None) -> None:
    if objects is not None:
        for key, *_ in plan.marks:
            objects.delete(key)
        for key, *_ in plan.threads:
            objects.delete(key)
    if db is not None and plan.rows:
        for row in plan.rows:
            db.execute(f"DELETE FROM {row.table} WHERE id=?", (row.pk,))  # noqa: S608 — таблица из своего списка
        db.commit()


# ---------- стенд: только чтение ----------


def stand_tickets(stand: str, targets: list[Target], http: httpx.Client) -> list[str]:
    """Заявки по проверкам списка, которые видит экземпляр стенда (его SQLite): есть — нужен перезапуск."""
    seen: list[str] = []
    for t in targets:
        r = http.get(f"{stand.rstrip('/')}/api/v2/vehicles/{t.vehicle}/tickets", timeout=60)
        r.raise_for_status()
        seen += [f"{t.vehicle}/{x['session_id']} {x['ticket_id']}" for x in r.json() if x["session_id"] in t.sessions]
    return seen


# ---------- вывод ----------


def render(plan: Plan, dry: bool, bucket: str | None, db_path: Path | None) -> str:
    verb = "будет удалено" if dry else "удалено"
    out: list[str] = []
    if bucket is not None:
        out.append(f"Бакет {bucket}:")
        out += [f"  нить     {k}  {v}/{s}, реплик {n}" for k, v, s, n in plan.threads] or ["  нитей списка нет"]
        out += [f"  отметка  {k}  {v}/{s}, {w}" for k, v, s, w in plan.marks] or ["  отметок заявок списка нет"]
        out.append(f"  не тронуто: чужих нитей {plan.other_threads}, отметок других заявок {len(plan.other_marks)}")
        if plan.unreadable:
            out.append(f"  не разобраны (не тронуты): {', '.join(plan.unreadable)}")
    if db_path is not None:
        out.append(f"SQLite {db_path}:")
        out += [f"  {r.table:<10} id={r.pk}  {r.vehicle}/{r.session}  {r.what}" for r in plan.rows] or [
            "  строк списка нет"
        ]
    by: dict[str, list[int]] = {}
    for _, v, _, _ in plan.threads:
        by.setdefault(v, [0, 0, 0])[0] += 1
    for _, v, _, _ in plan.marks:
        by.setdefault(v, [0, 0, 0])[1] += 1
    for r in plan.rows:
        by.setdefault(r.vehicle, [0, 0, 0])[2] += r.table == "tickets"
    out.append("")
    out.append(
        f"Итог ({verb}): нитей {len(plan.threads)}, отметок заявок {len(plan.marks)}, строк SQLite {len(plan.rows)}"
    )
    out += [f"  {v}: нитей {a}, отметок {b}, заявок в SQLite {c}" for v, (a, b, c) in sorted(by.items())]
    return "\n".join(out)


def book_rows(rows: list[dict[str, Any]], targets: list[Target]) -> list[dict[str, Any]]:
    """Строки общей книги заявок, относящиеся к проверкам списка (машина и номер проверки)."""
    want = {(t.vehicle, s) for t in targets for s in t.sessions}
    return [r for r in rows if (r.get("vehicle_id"), r.get("session_id")) in want]


def prune_book(bucket: Any, targets: list[Target], dry: bool) -> list[str]:
    """Убрать из `v2/sent-tickets.json` заявки проверок списка; вернуть их номера ТОиР. `dry` — только посчитать."""
    from service.spend import BucketObject
    from service.ticket_book import KEY, SharedTickets

    book = SharedTickets(BucketObject(bucket, KEY))
    found = [str(r.get("ticket_id") or r.get("id")) for r in book_rows(book.all(), targets)]
    if found and not dry:

        def drop(rows: list[dict[str, Any]]) -> bool:
            gone = book_rows(rows, targets)
            rows[:] = [r for r in rows if r not in gone]
            return bool(gone)

        book.change(drop)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reset_demo", description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="+", metavar="МАШИНА[/ПРОВЕРКА]", help="вместо списка по умолчанию")
    ap.add_argument("--dry-run", action="store_true", help="только показать, что будет удалено")
    ap.add_argument("--no-bucket", action="store_true", help="не трогать бакет")
    ap.add_argument("--no-db", action="store_true", help="не трогать локальную SQLite")
    ap.add_argument("--db", type=Path, help="путь к SQLite (по умолчанию STATE_DB или .state/agent.db)")
    ap.add_argument("--stand", help="адрес стенда: спросить (только чтение), видит ли он ещё заявки списка")
    args = ap.parse_args(argv)
    try:
        targets = parse_targets(args.only or DEFAULT, load_fleet())
    except ResetError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    print("Машины и проверки:", "; ".join(t.label() for t in targets))
    http = httpx.Client()
    bucket = os.environ.get("S3_BUCKET", "").strip() or None
    objects: Objects | None = None
    if args.no_bucket:
        bucket = None
    elif bucket is None:
        print("Бакет: S3_BUCKET не задан — пропущен (нужен .env со статическим ключом, как для make logs)")
    else:
        try:
            objects = S3Objects.from_env(http)
        except ResetError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 2
    db_path = None if args.no_db else (args.db or Path(os.environ.get("STATE_DB", ".state/agent.db")))
    db = None
    if db_path is not None and str(db_path) != ":memory:":
        if db_path.is_file():
            db = sqlite3.connect(str(db_path))
        else:
            print(f"SQLite: {db_path} нет — пропущена")
            db_path = None
    try:
        plan = make_plan(objects, db, targets)
        if not args.dry_run and not plan.empty():
            apply(plan, objects, db)
    except (ResetError, httpx.HTTPError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    finally:
        if db is not None:
            db.close()
    print(render(plan, args.dry_run, bucket, db_path))
    if isinstance(objects, S3Objects):
        try:
            booked = prune_book(objects.bucket, targets, args.dry_run)
            verb = "будет убрано" if args.dry_run else "убрано"
            print(
                f"Общая книга заявок v2/sent-tickets.json: {verb} {len(booked)}"
                + (f" ({', '.join(booked)})" if booked else "")
            )
        except Exception as exc:  # книга — дополнение к сбросу: её сбой остальное не отменяет
            print(f"❌ общая книга заявок: {type(exc).__name__}: {exc}", file=sys.stderr)
    if args.dry_run:
        print("\nСухой прогон: ничего не удалено. Удалить — без --dry-run.")
    seen: list[str] = []
    if args.stand:
        try:
            seen = stand_tickets(args.stand, targets, http)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            print(f"\nСтенд {args.stand}: не ответил ({type(exc).__name__}) — заявки экземпляра не проверены")
    print("\nРуками:")
    if seen:
        print(f"  Стенд ещё видит заявки ({'; '.join(seen)}): это SQLite и память его экземпляра.")
    elif args.stand:
        print("  Ответивший экземпляр стенда заявок списка не видит. Экземпляров несколько или был дубль — всё же:")
    print(
        "  Стенд: «Создать заявку» вернётся, когда экземпляры сменятся новой ревизией (их SQLite /tmp/agent.db и\n"
        "  нити в памяти), заодно перезапустится Mock ТОиР (заявки в памяти, номера снова с TKT-0001):\n"
        f"    {RESTART}\n"
        "  После зелёного запуска — ещё раз make reset-demo (старый экземпляр мог записать нить снова),\n"
        "  затем make demo-check. На телефоне — открыть машину заново."
    )
    print("  Локальный сервер: нити v2 у него в памяти — make stop-local && make run-local.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
