"""Журнал стенда за период (issue #27): скачать logs/<дата>/*.jsonl из бакета и свести.

  make logs                                 # сегодня по Москве
  make logs SINCE=2026-11-28 UNTIL=2026-12-03

Читает по статическому ключу из .env (S3_*) — только чтение. Сводка — в терминал и в .state/stand-logs-<период>.md
(вне git): старты экземпляров, запросы по маршрутам (число, 5xx, p50/p95 мс), шаги агента, ошибки по классам.
В журнале нет текста вопросов и персональных данных (белый список полей в service/stand_log.py).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from service import kb_store
from service.spend import MSK
from service.stand_log import PREFIX

ROOT = Path(__file__).resolve().parents[1]


def pct(values: list[float], q: float) -> int:
    if not values:
        return 0
    v = sorted(values)
    return int(v[min(len(v) - 1, round(q * (len(v) - 1)))])


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """События журнала → сводка (чистая функция, тестируется без бакета)."""
    starts = [e for e in events if e.get("kind") == "start"]
    instances = {e.get("instance") for e in events if e.get("instance")}
    uptime: dict[str, int] = defaultdict(int)
    routes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    steps: dict[str, list[dict[str, Any]]] = defaultdict(list)
    errors: Counter[str] = Counter()
    for e in events:
        kind = e.get("kind")
        if kind == "request":
            routes[f"{e.get('method', '')} {e.get('route', '-')}"].append(e)
        elif kind == "step" and e.get("step") == "uptime":
            inst = str(e.get("instance"))
            uptime[inst] = max(uptime[inst], int(e.get("uptime_s") or 0))
        elif kind == "step":
            steps[str(e.get("step"))].append(e)
        elif kind == "error":
            errors[f"{e.get('error')} · {e.get('method', '')} {e.get('route', '-')}"] += 1
    return {
        "events": len(events),
        "instances": len(instances),
        "starts": len(starts),
        "max_uptime_s": max(uptime.values(), default=0),
        "routes": {
            r: {
                "count": len(v),
                "5xx": sum(1 for e in v if int(e.get("status") or 0) >= 500),
                "4xx": sum(1 for e in v if 400 <= int(e.get("status") or 0) < 500),
                "p50": pct([float(e.get("ms") or 0) for e in v], 0.5),
                "p95": pct([float(e.get("ms") or 0) for e in v], 0.95),
            }
            for r, v in sorted(routes.items())
        },
        "steps": {
            s: {
                "count": len(v),
                "failed": sum(1 for e in v if e.get("ok") is False),
                "p50": pct([float(e.get("ms") or 0) for e in v], 0.5),
                "p95": pct([float(e.get("ms") or 0) for e in v], 0.95),
            }
            for s, v in sorted(steps.items())
        },
        "errors": dict(errors.most_common()),
    }


def render(period: str, s: dict[str, Any]) -> str:
    lines = [
        f"# Журнал стенда: {period}",
        "",
        f"Событий {s['events']}, экземпляров {s['instances']}, стартов (холодных) {s['starts']}, "
        f"наибольший аптайм {s['max_uptime_s'] // 60} мин.",
        "",
        "## Запросы",
        "",
        "| Маршрут | Число | 5xx | 4xx | p50, мс | p95, мс |",
        "|---|---|---|---|---|---|",
        *[
            f"| {r} | {v['count']} | {v['5xx']} | {v['4xx']} | {v['p50']} | {v['p95']} |"
            for r, v in s["routes"].items()
        ],
        "",
        "## Шаги агента",
        "",
        "| Шаг | Число | Сбоев | p50, мс | p95, мс |",
        "|---|---|---|---|---|",
        *[f"| {k} | {v['count']} | {v['failed']} | {v['p50']} | {v['p95']} |" for k, v in s["steps"].items()],
        "",
        "## Ошибки",
        "",
        *([f"- {k}: {n}" for k, n in s["errors"].items()] or ["Нет."]),
        "",
    ]
    return "\n".join(lines)


def list_keys(bucket: kb_store.Bucket, prefix: str) -> list[str]:
    keys: list[str] = []
    token = ""
    while True:
        query = f"list-type=2&prefix={prefix}" + (f"&continuation-token={token}" if token else "")
        url = f"{bucket.endpoint.rstrip('/')}/{bucket.bucket}?{query}"
        headers = bucket.auth("GET", url, {}, kb_store._sha256(b""))
        r = bucket.http.get(url, headers=headers, timeout=60)  # подписан тот же URL, что отправлен
        r.raise_for_status()
        keys += re.findall(r"<Key>([^<]+)</Key>", r.text)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", r.text)
        if not m:
            return keys
        token = m.group(1)


def main() -> int:
    today = datetime.now(MSK).date()
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=str(today))
    ap.add_argument("--until", default=str(today))
    args = ap.parse_args()
    key_id, secret = os.environ.get("S3_ACCESS_KEY_ID", ""), os.environ.get("S3_SECRET_ACCESS_KEY", "")
    name = os.environ.get("S3_BUCKET", "")
    if not (key_id and secret and name):
        raise SystemExit("нужны S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY (статический ключ, только чтение)")
    endpoint = os.environ.get("S3_ENDPOINT", kb_store.DEFAULT_ENDPOINT)
    bucket = kb_store.Bucket(name, kb_store.sigv4_auth(key_id, secret), httpx.Client(), endpoint)
    events: list[dict[str, Any]] = []
    day, until = date.fromisoformat(args.since), date.fromisoformat(args.until)
    while day <= until:
        for key in list_keys(bucket, f"{PREFIX}/{day.isoformat()}/"):
            for line in bucket.get(key).decode("utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
        day += timedelta(days=1)
    period = f"{args.since}…{args.until}"
    text = render(period, summarize(events))
    out = ROOT / ".state" / f"stand-logs-{args.since}_{args.until}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"сводка: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
