"""Норма и предел (issue #40 п. 2): если руководство даёт и норму исправного двигателя, и предел после длительной
эксплуатации — ответ показывает оба с пометкой, что есть что (например, давление масла ЯМЗ-236: 400–700 кПа —
норма, не ниже 300 кПа — предел). Блок строит код; цитаты сверяются со страницами — без этого блока нет."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from service.contradictions import Quote
from service.fault_matrix import normalize
from service.manuals.catalog import canonical_engine

PATH = Path(__file__).resolve().parents[2] / "data" / "norm_limits.json"
HEADER = "📏 Норма и предел"


@dataclass(frozen=True)
class NormLimit:
    id: str
    engines: tuple[str, ...]
    topic: re.Pattern[str]
    title: str
    norm: Quote
    limit: Quote


@lru_cache(maxsize=1)
def items() -> tuple[NormLimit, ...]:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    return tuple(
        NormLimit(
            id=i["id"],
            engines=tuple(i["engines"]),
            topic=re.compile(i["topic"], re.I),
            title=i["title"],
            norm=Quote(i["norm"]["doc"], int(i["norm"]["page"]), i["norm"]["quote"]),
            limit=Quote(i["limit"]["doc"], int(i["limit"]["page"]), i["limit"]["quote"]),
        )
        for i in data["items"]
    )


def match(engine: str, question: str) -> NormLimit | None:
    canon = canonical_engine(engine)
    return next((n for n in items() if canon in n.engines and n.topic.search(question)), None)


def verified(n: NormLimit, page_text: Callable[[str, int], str | None] | None) -> bool:
    if page_text is None:
        return False
    for q in (n.norm, n.limit):
        text = page_text(q.doc, q.page)
        if not text or normalize(q.quote) not in normalize(text):
            return False
    return True


def block(n: NormLimit, refs: dict[tuple[str, int], str]) -> str:
    def line(label: str, q: Quote) -> str:
        ref = refs.get((q.doc, q.page))
        return f"- {label}: «{q.quote}» — {q.label()}" + (f" [{ref}]" if ref else "")

    return "\n".join(
        [
            f"{HEADER} — {n.title}:",
            line("Норма (исправный прогретый двигатель)", n.norm),
            line("Предел после длительной эксплуатации — ниже него нужна дефектовка", n.limit),
        ]
    )
