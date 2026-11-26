"""Проверка условной записи Yandex Object Storage на настоящем бакете (issue #11). Запускает человек.

  make spend-probe            # по статическому ключу из .env (S3_*), объект spend/probe-<время>.json

8 потоков × 25 прибавок по 0,01 ₽ через тот же SharedLedger, что на стенде, в отдельный объект — общий счётчик
стенда (spend/ledger.json) не трогается. Сумма должна сойтись ровно в 2,00 ₽; иначе условная запись бакета не
атомарна и счётчик на стенде может терять суммы. Объект после проверки удаляется.
"""

from __future__ import annotations

import os
import sys
import threading
import time

import httpx

from service import kb_store
from service.spend import BucketObject, SharedLedger

THREADS, ADDS, RUB = 8, 25, 0.01


def main() -> int:
    key_id, secret = os.environ.get("S3_ACCESS_KEY_ID", ""), os.environ.get("S3_SECRET_ACCESS_KEY", "")
    name = os.environ.get("S3_BUCKET", "")
    if not (key_id and secret and name):
        raise SystemExit("нужны S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY")
    http = httpx.Client()
    endpoint = os.environ.get("S3_ENDPOINT", kb_store.DEFAULT_ENDPOINT)
    bucket = kb_store.Bucket(name, kb_store.sigv4_auth(key_id, secret), http, endpoint)
    key = f"spend/probe-{int(time.time())}.json"
    obj = BucketObject(bucket, key)
    conflicts = [0]
    write = obj.write

    def counting_write(data: bytes, if_match: str | None) -> int:
        status = write(data, if_match)
        if status in (409, 412):
            conflicts[0] += 1
        return status

    obj.write = counting_write  # type: ignore[method-assign]

    def work() -> None:
        led = SharedLedger(obj)  # свой «экземпляр» на поток
        for _ in range(ADDS):
            led.add(RUB, time.time())
        for _ in range(20):  # остаток после 8 конфликтов подряд — дожать (на стенде он уходит со следующей записью)
            if not led._pending:
                break
            led._flush()

    threads = [threading.Thread(target=work) for _ in range(THREADS)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = SharedLedger(obj).spent_total()
    expected = THREADS * ADDS * RUB
    url = kb_store.object_url(endpoint, name, key)
    http.delete(url, headers=bucket.auth("DELETE", url, {}, kb_store._sha256(b"")))
    ok = abs(total - expected) < 1e-6
    print(f"{key}: {total:.2f} ₽ из {expected:.2f}, конфликтов {conflicts[0]}, {time.monotonic() - t0:.1f} с — "
          f"{'условная запись атомарна' if ok else 'СУММЫ ПОТЕРЯНЫ: условная запись не атомарна'}")  # fmt: skip
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
