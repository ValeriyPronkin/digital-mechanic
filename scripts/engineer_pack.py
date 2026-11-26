"""Пакет для инженера (#40 п. 7): прогон всех отклонений и сбоев на стенде → один HTML для проверки и доп. материалов.

    python scripts/engineer_pack.py https://<стенд>/ [--out reports/engineer-pack.html] [--limit N]

По каждой проверке со статусом `anomaly` или `check_failed`: карточка (вердикт, срочность с основанием, класс опасности,
плашки, посторонний текст в описании), ответ помощника на вопрос механика, черновик заявки или причина отказа,
страницы руководства с цитатами, токены и ₽ из паспорта запроса (#31). Оглавление — по группам: несовместимые,
помехи, класс 3, остальные отклонения, сбои записи. Заявки в ТОиР не отправляются — только черновики.

Стенд ограничивает частоту вопросов (10 в минуту с адреса): скрипт выдерживает паузу и повторяет после 429.
Полный прогон (84 проверки) — ≈ 15 минут и ≈ 11 ₽ на модель (проба 26.11: 0,13 ₽ на проверку).
"""

from __future__ import annotations

import argparse
import html
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

QUESTION = {"anomaly": "Оформи заявку на дефектовку", "check_failed": "Что с двигателем?"}
PAUSE_S = 6.5  # 10 вопросов в минуту с адреса — лимит стенда (D-12)
GROUPS = [
    ("incompatible", "Код не подходит к двигателю"),
    ("noisy", "Запись с помехами"),
    ("class3", "Класс опасности 3"),
    ("anomaly", "Остальные отклонения"),
    ("check_failed", "Сбой записи"),
]


def group_of(card: dict[str, Any]) -> str:
    if card["status"] == "check_failed":
        return "check_failed"
    if not card.get("compatible", True):
        return "incompatible"
    if any("помех" in b.lower() for b in card.get("banners") or []):
        return "noisy"
    if card.get("danger_class") == 3:
        return "class3"
    return "anomaly"


def _post(c: httpx.Client, url: str, body: dict[str, Any], retries: int = 6) -> httpx.Response:
    for _ in range(retries):
        r = c.post(url, json=body)
        if r.status_code != 429:
            return r
        time.sleep(float(r.headers.get("Retry-After") or PAUSE_S) + 0.5)
    return r


def collect(c: httpx.Client, base: str, limit: int | None = None, pause: float = PAUSE_S) -> list[dict[str, Any]]:
    base = base.rstrip("/")
    rows: list[dict[str, Any]] = []
    vehicles = c.get(f"{base}/api/vehicles").json()
    for v in vehicles:
        hist = c.get(f"{base}/api/vehicles/{v['vehicle_id']}").json()
        for s in reversed(hist["sessions"]):  # по порядку проверок
            card = _post(c, f"{base}/api/diagnose", {"vehicle_id": v["vehicle_id"], "session_id": s["session_id"]})
            if card.status_code != 200:
                continue
            cj = card.json()
            if cj["status"] not in QUESTION:
                continue
            if limit is not None and len(rows) >= limit:
                return rows
            q = QUESTION[cj["status"]]
            ask = {"vehicle_id": v["vehicle_id"], "session_id": s["session_id"], "message": q}
            r = _post(c, f"{base}/api/chat", ask)
            answer = r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
            rows.append({"vehicle": v, "session": s, "card": cj, "question": q, "answer": answer})
            print(f"{len(rows):3d} {v['vehicle_id']} {s['session_id']} {cj['status']} {cj.get('fault_code') or ''}",
                  file=sys.stderr)  # fmt: skip
            time.sleep(pause)
    return rows


def refusal(answer: dict[str, Any], card: dict[str, Any]) -> str | None:
    """Почему заявки нет: отказ инструмента «черновик заявки» из паспорта, иначе — правило карточки."""
    if answer.get("draft"):
        return None
    for t in (answer.get("passport") or {}).get("tools") or []:
        if t.get("tool") == "draft_ticket" and t.get("refused"):
            return str(t["refused"])
    if not card.get("ticket_possible"):
        return card.get("action") or "заявка по этому результату не оформляется"
    return "черновик не подготовлен — см. ответ помощника"


E = html.escape


def _card_html(row: dict[str, Any], n: int) -> str:
    v, s, card, ans = row["vehicle"], row["session"], row["card"], row["answer"]
    head = f"{n}. {v['vehicle_id']} · {v['engine_model']} · {s['session_id']} — {card['title']}"
    parts = [f'<section class="check" id="c{n}"><h3>{E(head)}</h3>', '<table class="kv">']
    danger = f" · класс опасности {card['danger_class']}" if card.get("danger_class") else ""
    kv = [
        ("Вердикт", card["action"]),
        ("Код", (card.get("fault_code") or "—") + danger),
        ("Уверенность", f"{card['confidence_pct']}%" if card.get("confidence_pct") is not None else "—"),
        ("Срочность", f"{card['urgency']} — {card['urgency_reason']}" if card.get("urgency") else "—"),
        ("Плашки", "; ".join(card.get("banners") or []) or "—"),
        ("Тенденция", card.get("trend") or "—"),
        ("Сообщение сервиса", card.get("ml_quote") or "—"),
    ]
    if card.get("ml_injection"):
        kv.append(("Посторонний текст (отложен, не выполнен)", card["ml_injection"]))
    if card.get("design_fact"):
        f = card["design_fact"]
        kv.append(("Факт о конструкции", f"{f['text']} — {f['manual']}, стр. {f['pdf_page']}: «{f['quote']}»"))
    parts += [f"<tr><th>{E(k)}</th><td>{E(str(val))}</td></tr>" for k, val in kv]
    parts.append("</table>")
    if "error" in ans:
        parts.append(f'<p class="err">Ответ не получен: {E(ans["error"])}</p></section>')
        return "".join(parts)
    parts.append(f'<h4>Вопрос механика: «{E(row["question"])}»</h4><div class="answer">{E(ans.get("text", ""))}</div>')
    for note in ans.get("notes") or []:
        parts.append(f'<p class="note">⚠ {E(note)}</p>')
    draft = ans.get("draft")
    if draft:
        b = draft["body"]
        parts.append(f"<h4>Черновик заявки · срочность {E(b['urgency'])} — {E(draft['urgency_reason'])}</h4><ol>")
        parts += [f"<li>{E(o)}</li>" for o in b["operations"]]
        refs = ", ".join(f"{r['manual']}, стр. {r['pdf_page']}" for r in b["references"])
        parts.append(f"</ol><p><b>Источники заявки:</b> {E(refs)}</p>")
    else:
        parts.append(f'<p class="refused"><b>Заявки нет:</b> {E(refusal(ans, card) or "")}</p>')
    srcs = ans.get("sources") or []
    if srcs:
        parts.append("<details><summary>Страницы руководства в ответе (" + str(len(srcs)) + ")</summary>")
        for src in srcs:
            section = " · " + E(src["section"]) if src.get("section") else ""
            cite = f"{E(src['manual'])}, стр. PDF {src['pdf_page']}{section}"
            parts.append(f"<blockquote><cite>{cite}</cite>{E(src.get('quote') or '')}</blockquote>")
        parts.append("</details>")
    t = (ans.get("passport") or {}).get("total") or {}
    tr = ans.get("trace") or {}
    model_rub = t.get("model_rub", tr.get("cost_rub", 0))
    tokens = f"{tr.get('tokens_in', 0)} / {tr.get('tokens_out', 0)}"
    parts.append(
        f'<p class="cost">Токены {tokens} · модель {model_rub:.4f} ₽ · '
        f"всего {t.get('total_rub', 0):.4f} ₽</p></section>"
    )
    return "".join(parts)


CSS = """body{font:15px/1.45 system-ui,sans-serif;max-width:60rem;margin:1rem auto;padding:0 1rem;color:#1f2933}
h1{font-size:1.4rem}h2{margin-top:2rem;border-bottom:2px solid #1f2933}h3{font-size:1.05rem;margin:1.4rem 0 .4rem}
table{border-collapse:collapse;width:100%}th,td{border-top:1px solid #d9dee5;padding:.25rem .4rem;text-align:left;
vertical-align:top}th{width:16rem;color:#5f6b7a;font-weight:600}.answer{white-space:pre-wrap;background:#f4f5f7;
padding:.6rem;border-radius:8px}blockquote{margin:.4rem 0;padding:.4rem .7rem;border-left:4px solid #e5c46b;
background:#fffdf5;white-space:pre-wrap}cite{display:block;color:#5f6b7a;font-style:normal;font-size:.85rem}
.note{color:#5c4300}.refused{color:#b42318}.err{color:#b42318}.cost{color:#5f6b7a;font-size:.88rem}
.check{border:1px solid #d9dee5;border-radius:10px;padding:.2rem .9rem .6rem;margin:.8rem 0}"""


def render(rows: list[dict[str, Any]], base: str, started: datetime) -> str:
    by_group: dict[str, list[tuple[int, dict[str, Any]]]] = {g: [] for g, _ in GROUPS}
    for n, row in enumerate(rows, 1):
        by_group[group_of(row["card"])].append((n, row))
    drafts = sum(1 for r in rows if r["answer"].get("draft"))
    errors = sum(1 for r in rows if "error" in r["answer"])
    rub = sum(((r["answer"].get("passport") or {}).get("total") or {}).get("total_rub", 0) for r in rows)
    out = ["<!doctype html><html lang=ru><meta charset=utf-8><title>Пакет для инженера — Цифровой механик</title>",
           f"<style>{CSS}</style><h1>Пакет для инженера — Цифровой механик</h1>",
           f"<p>Стенд: {E(base)} · прогон {started:%d.%m.%Y %H:%M} · проверок {len(rows)} · "
           f"черновиков заявок {drafts} · "
           f"ошибок ответа {errors} · ₽ на прогон {rub:.2f} (без НДС, по паспортам запросов)</p>",
           "<p>Заявки в ТОиР не отправлялись — показаны черновики, которые механик подтвердил бы кнопкой.</p>",
           "<h2>Оглавление</h2><ul>"]  # fmt: skip
    for g, title in GROUPS:
        items = by_group[g]
        links = ", ".join(f'<a href="#c{n}">{E(r["vehicle"]["vehicle_id"])} {E(r["session"]["session_id"])}</a>'
                          for n, r in items)  # fmt: skip
        out.append(f'<li><a href="#g-{g}"><b>{E(title)}</b></a> — {len(items)}: {links or "нет"}</li>')
    out.append("</ul>")
    for g, title in GROUPS:
        out.append(f'<h2 id="g-{g}">{E(title)} ({len(by_group[g])})</h2>')
        out += [_card_html(r, n) for n, r in by_group[g]]
    return "".join(out) + "</html>"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="engineer_pack")
    p.add_argument("url", help="адрес стенда, например https://<id>.containers.yandexcloud.net/")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--limit", type=int, default=None, help="первые N проверок (для пробы)")
    args = p.parse_args(argv)
    started = datetime.now()
    out = args.out or Path("reports") / f"engineer-pack-{started:%Y-%m-%d-%H%M}.html"
    with httpx.Client(timeout=180) as c:
        rows = collect(c, args.url, args.limit)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(rows, args.url, started), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
