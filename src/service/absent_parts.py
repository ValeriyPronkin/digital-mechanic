"""Узлы, которых у двигателя нет (ТЗ F4; приёмка «нет в руководстве»).

Вопрос о таком узле — ответ строит код, а не модель: «у <двигатель> нет <узел>», цитаты из руководства этого двигателя
со страницами, проверка и регулировка не применимы, при признаках неисправности — дефектовка. Без советов модели и без
чужих цифр: модель под пометкой «мнение помощника» советовала работы с узлом, которого нет (приёмка v2, 4/9).
Таблица — `data/absent_parts.json`; цитаты сверяются со страницами, без подтверждённой цитаты ответ не строится.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from service.fault_matrix import all_cells, normalize
from service.manuals.catalog import canonical_engine

PATH = Path(__file__).resolve().parents[2] / "data" / "absent_parts.json"
PageText = Callable[[str, int], str | None]
NOT_APPLICABLE = "Проверка и регулировка этого узла к вашему двигателю не применимы."
ADVICE = "Если есть признаки неисправности (стук, дым, потеря мощности) — оформите дефектовку, там определят причину."


@dataclass(frozen=True)
class Quote:
    doc: str
    page: int
    quote: str


@dataclass(frozen=True)
class Absent:
    id: str
    engines: tuple[str, ...]
    question: re.Pattern[str]
    part: str
    statement: str
    quotes: tuple[Quote, ...]
    absent_on: tuple[str, tuple[int, ...], re.Pattern[str]] | None


@lru_cache(maxsize=1)
def items() -> tuple[Absent, ...]:
    """Свои записи (чего нет в матрице) и ячейки матрицы «узла нет» — факт о конструкции с цитатой (#40 п. 3)."""
    data = json.loads(PATH.read_text(encoding="utf-8"))
    out = []
    for i in data["items"]:
        ao = i.get("absent_on")
        out.append(
            Absent(
                id=i["id"],
                engines=tuple(i["engines"]),
                question=re.compile(i["question"], re.I),
                part=i["part"],
                statement=i["statement"],
                quotes=tuple(Quote(q["doc"], int(q["page"]), q["quote"]) for q in i["quotes"]),
                absent_on=(ao["doc"], tuple(ao["pages"]), re.compile(ao["pattern"], re.I)) if ao else None,
            )
        )
    nodes = {k: v for k, v in data.get("matrix_nodes", {}).items() if not k.startswith("_")}
    for cell in all_cells():
        node = nodes.get(cell.code)
        if cell.applicable != "false" or cell.basis is None or node is None:
            continue
        b = cell.basis
        out.append(
            Absent(
                id=f"matrix-{cell.code}-{cell.engine}",
                engines=(cell.engine,),
                question=re.compile(node["question"], re.I),
                part=node["part"],
                statement=cell.why[:1].upper() + cell.why[1:] + ".",
                quotes=(Quote(b.doc, b.page, b.quote),),
                absent_on=None,
            )
        )
    return tuple(out)


def match(engine: str, question: str) -> Absent | None:
    canon = canonical_engine(engine)
    for a in items():
        if canon in a.engines and a.question.search(question):
            return a
    return None


def verified(a: Absent, page_text: PageText | None) -> list[Quote] | None:
    """Цитаты, найденные на своих страницах; None — проверить нельзя или что-то не сошлось (тогда ответ — моделью)."""
    if page_text is None:
        return None
    quotes = []
    for q in a.quotes:
        text = page_text(q.doc, q.page)
        if not text or normalize(q.quote) not in normalize(text):
            return None
        quotes.append(q)
    if a.absent_on is not None:
        doc, pages, pattern = a.absent_on
        for p in pages:
            text = page_text(doc, p)
            if text is None or pattern.search(text):
                return None
    return quotes


def answer(
    engine: str, a: Absent, quotes: list[Quote], refs: dict[tuple[str, int], str], label: Callable[[Quote], str]
) -> str:
    lines = [f"**У {engine} нет {a.part}.** {a.statement}", "", "По руководству этого двигателя:"]
    for q in quotes:
        ref = refs.get((q.doc, q.page))
        lines.append(f"- {label(q)}: «{q.quote}»" + (f" [{ref}]" if ref else ""))
    lines += ["", NOT_APPLICABLE, ADVICE]
    return "\n".join(lines)
