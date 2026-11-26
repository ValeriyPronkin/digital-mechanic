"""С1 на стенде на настоящей модели: вопрос → «Оформи заявку» → отправка по отпечатку (≈0,4 ₽).

python scripts/stand_c1.py https://<стенд>/  — код 0, если заявка создана и все ссылки — на руководства ЯМЗ-236.
Запускается из workflow Stand (флаг c1_live): с площадки Wi-Fi подменяет TLS.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

VEHICLE, SESSION = "M333YK47", "S-0005"


def main(url: str) -> int:
    base = url.rstrip("/")
    state: str | None = None
    with httpx.Client(timeout=180) as c:

        def chat(msg: str) -> dict[str, Any]:
            nonlocal state
            r = c.post(
                f"{base}/api/chat", json={"vehicle_id": VEHICLE, "session_id": SESSION, "message": msg, "state": state}
            )
            r.raise_for_status()
            body: dict[str, Any] = r.json()
            state = body.pop("state")
            print(f"\n>>> {msg}\n{body['text']}\nnotes: {body.get('notes')}")
            print("источники:", [(s["manual"], s["pdf_page"]) for s in body.get("sources", [])])
            return body

        chat("Что случилось с двигателем? Объясни по шагам.")
        draft = chat("Оформи заявку на дефектовку.").get("draft")
        if not draft:
            print("С1: черновика заявки нет", file=sys.stderr)
            return 1
        print(json.dumps(draft["body"], ensure_ascii=False, indent=1))
        r = c.post(f"{base}/api/tickets", json={"state": state, "fingerprint": draft["fingerprint"]})
        ticket = {k: v for k, v in r.json().items() if k != "state"}
        print("заявка:", r.status_code, ticket)
    refs = draft["body"].get("references", [])
    own = all(ref["manual"].startswith("ЯМЗ-236") for ref in refs)  # двигатель машины — ЯМЗ-236М2
    ok = r.status_code == 201 and bool(refs) and own
    print("С1:", "ок" if ok else "НЕ ПРОШЁЛ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
