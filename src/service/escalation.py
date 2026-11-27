"""Противоречия руководств — эскалация главному механику, а не совет механику (встреча с заказчиком 27.11, Валерий).

Механик, увидевший противоречие, ничего не «уточняет» сам: система ставит противоречие в очередь главного механика
и показывает «Передано главному механику на решение (№ N). Пока — безопасное правило: …». Главный механик (или
поддержка) отправляет вопрос дальше — заводу-изготовителю или в поддержку — и фиксирует ответ:

  open      — всплыло в ответе механику (сколько раз, на каких машинах);
  sent      — отправлено: кому (завод-изготовитель / поддержка), когда, кто, текст обращения (черновик письма
              собирает код: двигатель, обе формулировки с документами и страницами, вопрос);
  resolved  — ответ: текст, источник, кто зафиксировал, когда, документ-основание.

После `resolved` агент показывает «Решение по противоречию (источник: …, дата): …» РЯДОМ с обеими формулировками
(не вместо них). Письмо код не отправляет: только черновик и отметка «отправлено»; канал отправки — настройка
`CONTRADICTION_CHANNEL` (пилот; по умолчанию `none`).

Хранение — как у долгой сессии (`case_log`): очередь `v2/contradictions/queue.json` — условная запись с ETag;
журнал решений `v2/contradictions/journal/NNNNNN.json` — только добавление, с цепочкой хэшей.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from service.case_log import MAX_TRIES, Backend, BucketBackend, MemoryBackend, append_chain, now_iso, read_chain

log = logging.getLogger(__name__)

QUEUE_KEY = "v2/contradictions/queue.json"
JOURNAL = "v2/contradictions/journal"
Target = Literal["manufacturer", "support"]
TARGET_WORD = {"manufacturer": "завод-изготовитель", "support": "поддержка", "chief_mechanic": "главный механик"}
# правило до решения выводится из самих страниц (`contradictions.safe_rule`, ответ организаторов 27.11) и стоит в ответе
# строкой «Безопасное правило:» над строкой эскалации; «до решения не выбирать ничего» механику не говорится
NO_RULE = "безопасное правило из страниц руководства — строкой выше в ответе"
MAX_VEHICLES = 20


def safe_rule(conclusion: str) -> str:
    """Безопасное правило до решения — как оно выведено из страниц (агент передаёт его в `report` как conclusion)."""
    return conclusion.rstrip(".") if conclusion else NO_RULE


def escalation_line(item: dict[str, Any]) -> str:
    """Строка под формулировками: решение (с источником и датой) или «передано на решение» и безопасное правило."""
    res = item.get("resolution")
    if item.get("status") == "resolved" and res:
        when = datetime.fromisoformat(res["at"]).strftime("%d.%m.%Y")
        src = TARGET_WORD.get(res.get("source") or "", res.get("source") or "главный механик")
        doc = f" Основание: {res['document']}." if res.get("document") else ""
        return f"Решение по противоречию (источник: {src}, {when}): {res['text'].rstrip('.')}.{doc}"
    # правило уже написано строкой «Безопасное правило:» выше — не повторяем; полный текст — в очереди и в письме
    return f"Передано главному механику на решение (№ {item['number']}). Пока — по безопасному правилу выше."


class ContradictionQueue:
    def __init__(self, backend: Backend | None = None, clock: Callable[[], float] = time.time) -> None:
        self.backend: Backend = backend or MemoryBackend()
        self.clock = clock

    @classmethod
    def from_env(cls) -> ContradictionQueue:
        """На стенде (`V2_STATE_BUCKET=1`) — бакет по IAM, общий для экземпляров; иначе — в памяти."""
        if os.environ.get("V2_STATE_BUCKET", "") != "1" or not os.environ.get("S3_BUCKET", "").strip():
            return cls()
        from service.case_log import CaseLog

        backend = CaseLog.from_env().backend
        return cls(backend if isinstance(backend, BucketBackend) else None)

    # ---- очередь: чтение и условная запись ----
    def _load(self) -> tuple[dict[str, Any], str | None]:
        raw, etag = self.backend.read(QUEUE_KEY)
        return (json.loads(raw) if raw else {"next": 1, "items": {}}), etag

    def _update(self, change: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any] | None:
        for _ in range(MAX_TRIES):
            queue, etag = self._load()
            item = change(queue)
            if item is None:
                return None
            data = json.dumps(queue, ensure_ascii=False, sort_keys=True).encode("utf-8")
            if self.backend.replace(QUEUE_KEY, data, etag) if etag else self.backend.create(QUEUE_KEY, data):
                return item
        raise RuntimeError(f"очередь противоречий: не удалось записать за {MAX_TRIES} попыток")

    # ---- противоречие всплыло в ответе ----
    def report(self, k: Any, quotes: list[Any], engine: str, vehicle_id: str) -> dict[str, Any]:
        """Поставить в очередь (или посчитать ещё раз). `k` — `contradictions.Known`, `quotes` — подтверждённые
        цитаты."""
        now = now_iso(self.clock())

        def change(queue: dict[str, Any]) -> dict[str, Any]:
            item = queue["items"].get(k.id)
            if item is None:
                item = {
                    "id": k.id,
                    "number": queue["next"],
                    "status": "open",
                    "engine": engine,
                    "title": k.title,
                    "formulations": [
                        {"label": q.label(), "manual_id": q.doc, "pdf_page": q.page, "quote": q.quote} for q in quotes
                    ],
                    "rule": k.conclusion or None,
                    "safe_rule": safe_rule(k.conclusion),
                    "first_seen": now,
                    "count": 0,
                    "vehicles": [],
                }
                queue["next"] += 1
                queue["items"][k.id] = item
            item["count"] += 1
            item["last_seen"] = now
            if vehicle_id not in item["vehicles"] and len(item["vehicles"]) < MAX_VEHICLES:
                item["vehicles"].append(vehicle_id)
            return dict(item)

        item = self._update(change)
        if item is None:  # change() всегда возвращает строку очереди
            raise RuntimeError("очередь противоречий: пустая запись")
        return item

    # ---- главный механик ----
    def items(self, status: str = "open") -> list[dict[str, Any]]:
        rows = list(self._load()[0]["items"].values())
        if status != "all":
            rows = [r for r in rows if r["status"] == status]
        return sorted(rows, key=lambda r: (-r["count"], r["number"]))

    def get(self, number: int) -> dict[str, Any] | None:
        return next((r for r in self._load()[0]["items"].values() if r["number"] == number), None)

    def letter(self, item: dict[str, Any], to: Target = "manufacturer") -> str:
        """Черновик обращения: двигатель, обе формулировки с документами и страницами, вопрос."""
        lines = [
            f"Кому: {TARGET_WORD[to]}",
            f"Тема: противоречие в документации двигателя {item['engine']} — {item['title']}",
            "",
            "Здравствуйте.",
            "",
            f"В документации двигателя {item['engine']} формулировки по теме «{item['title']}» расходятся:",
        ]
        for i, f in enumerate(item["formulations"], 1):
            lines.append(f"{i}. {f['label']} (стр. PDF {f['pdf_page']}): «{f['quote']}»")
        lines += [
            "",
            f"Просим указать, какая формулировка верна для двигателя {item['engine']} "
            "(с учётом модификации и комплектации) и документ-основание "
            "(номер извещения об изменении, письма или редакции руководства).",
            f"До ответа механики работают по безопасному правилу: {item['safe_rule']}.",
            "",
            f"Противоречие № {item['number']} в журнале «Цифрового механика»: всплывало {item['count']} раз(а), "
            f"машины: {', '.join(item['vehicles']) or '—'}.",
        ]
        return "\n".join(lines)

    def send(self, number: int, to: Target, by: str, text: str | None = None) -> dict[str, Any] | None:
        """Отметка «отправлено» (код письмо не отправляет): кому, кто, когда и текст обращения."""
        now = now_iso(self.clock())

        def change(queue: dict[str, Any]) -> dict[str, Any] | None:
            item = next((r for r in queue["items"].values() if r["number"] == number), None)
            if item is None:
                return None
            body = text or self.letter(item, to)
            item["status"] = "sent" if item["status"] != "resolved" else "resolved"
            item.setdefault("sent", []).append({"to": to, "by": by, "at": now, "text": body, "channel": channel()})
            return dict(item)

        item = self._update(change)
        if item is not None:
            self._journal({"event": "sent", "number": number, "id": item["id"], **item["sent"][-1]})
        return item

    def resolve(
        self, number: int, text: str, by: str, source: str = "manufacturer", document: str | None = None
    ) -> dict[str, Any] | None:
        now = now_iso(self.clock())

        def change(queue: dict[str, Any]) -> dict[str, Any] | None:
            item = next((r for r in queue["items"].values() if r["number"] == number), None)
            if item is None:
                return None
            item["status"] = "resolved"
            item["resolution"] = {"text": text, "by": by, "at": now, "source": source, "document": document}
            return dict(item)

        item = self._update(change)
        if item is not None:
            self._journal({"event": "resolved", "number": number, "id": item["id"], **item["resolution"]})
        return item

    # ---- журнал решений: только добавление ----
    def _journal(self, event: dict[str, Any]) -> None:
        try:
            append_chain(self.backend, JOURNAL, event, self.clock)
        except Exception as exc:  # очередь уже записана; журнал — след, сбой не теряет решение
            log.warning("журнал противоречий не записан: %s", type(exc).__name__)

    def journal(self) -> list[dict[str, Any]]:
        return read_chain(self.backend, JOURNAL)


def channel() -> str:
    """Канал отправки обращения — настройка пилота; сейчас письмо не отправляется (`none`)."""
    return os.environ.get("CONTRADICTION_CHANNEL", "none").strip() or "none"
