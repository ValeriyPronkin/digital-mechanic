"""Противоречивые инструкции в руководствах одного двигателя (требование заказчика, 26.11).

Агент не выбирает одну формулировку как бесспорную: показывает все дословно с документом и страницей, отмечает
«Противоречие в документации» и рекомендует уточнить у производителя двигателя для своей модификации (правило заказчика
27.11: «к специалисту» не подходит — механик сам специалист).

Два слоя, оба — кодом:
1. Известные противоречия (`data/contradictions.json`): по двигателю и теме вопроса код сам строит блок с цитатами
   и выводом, принятым заказчиком; цитаты сверены со страницами (тест на индексе).
2. Противоречие, которое заметила модель: блок «Противоречие в документации» с цитатами «…» [R…] — код сверяет
   каждую цитату с текстом страницы её ссылки; меньше двух подтверждённых цитат — блок убирается
   (противоречие без доказательства не заявляем).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from service.fault_matrix import normalize
from service.manuals.catalog import DOCS_BY_ID, canonical_engine

PATH = Path(__file__).resolve().parents[2] / "data" / "contradictions.json"
HEADER = "⚠ Противоречие в документации"
ADVICE = "Для вашей модификации двигателя уточните у производителя двигателя."
_DOC_SHORT = {"re": "РЭ", "rk": "РК"}


@dataclass(frozen=True)
class Quote:
    doc: str
    page: int
    quote: str

    def label(self) -> str:
        short = _DOC_SHORT.get(self.doc.rsplit("-", 1)[-1], "")
        name = DOCS_BY_ID[self.doc].designation if self.doc in DOCS_BY_ID else self.doc
        return f"{short + ' — ' if short else ''}{name}, стр. {self.page}"


@dataclass(frozen=True)
class Known:
    id: str
    engines: tuple[str, ...]
    topic: re.Pattern[str]
    trigger: re.Pattern[str]
    claim: re.Pattern[str]  # утверждение по спорной теме в ответе модели (выбор одной формулировки)
    safe_line: str  # чем заменить такую строку ответа
    title: str
    quotes: tuple[Quote, ...]
    conclusion: str
    basis: str


@lru_cache(maxsize=1)
def known() -> tuple[Known, ...]:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    return tuple(
        Known(
            id=i["id"],
            engines=tuple(i["engines"]),
            topic=re.compile(i["topic"], re.I),
            trigger=re.compile(i["trigger"], re.I),
            claim=re.compile(i["claim"], re.I),
            safe_line=i["safe_line"],
            title=i["title"],
            quotes=tuple(Quote(q["doc"], int(q["page"]), q["quote"]) for q in i["quotes"]),
            conclusion=i["conclusion"],
            basis=i["basis"],
        )
        for i in data["items"]
    )


def match(engine: str, question: str) -> Known | None:
    canon = canonical_engine(engine)
    for k in known():
        if canon in k.engines and k.topic.search(question) and k.trigger.search(question):
            return k
    return None


def match_answer(engine: str, answer: str) -> Known | None:
    """Вопрос был о другом, но ответ сам заговорил о спорной теме (например, «не позже 15 мин»)."""
    canon = canonical_engine(engine)
    for k in known():
        if canon in k.engines and k.topic.search(answer) and k.claim.search(answer):
            return k
    return None


_SENT = re.compile(r"(?<=[.!?])\s+")
_LIST_PREFIX = re.compile(r"^(\s*(?:\d+[.)]|[-*•])\s+)")
_NO_CONTRADICTION = re.compile(r"противоречи\w* (?:в документации )?нет", re.I)
_ADVICE_DUP = re.compile(r"^\s*(?:\W\s*)?уточните у (?:специалиста|производителя)", re.I)
_CONCLUSION = re.compile(r"^\s*\**Вывод\**:", re.I)


def neutralize(k: Known, text: str) -> str:
    """Ответ модели рядом с блоком кода: строки, где модель выбрала одну формулировку по спорной теме, — вывод
    заказчика со ссылкой на блок; «противоречий нет», свой «Вывод:» и повтор совета — убрать."""
    out: list[str] = []
    for ln in text.split("\n"):
        if _NO_CONTRADICTION.search(ln) or _ADVICE_DUP.search(ln) or _CONCLUSION.search(ln):
            continue
        if k.claim.search(ln):
            m = _LIST_PREFIX.match(ln)
            prefix = m.group(1) if m else ""
            # заменяется только фраза о сроке: остальное в строке (значение зазора, ссылка) остаётся
            parts = [p for p in _SENT.split(ln[len(prefix) :]) if p.strip()]
            kept = [p for p in parts if not k.claim.search(p)]
            safe_seen = any(k.safe_line in o for o in out)
            if safe_seen and not kept and not re.match(r"\s*\d", prefix):
                continue  # вывод уже есть; нумерованный шаг оставляем — нумерация не ломается
            if not prefix and safe_seen:
                if not kept:
                    continue  # вне списка вывод — один раз
                ln = " ".join(kept)
            else:
                ln = prefix + " ".join([*kept, k.safe_line])
        out.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def verified_quotes(k: Known, page_text: Callable[[str, int], str | None] | None) -> list[Quote]:
    """Только цитаты, которые есть на своей странице. Без текста страниц (нет индекса) — ничего не заявляем."""
    if page_text is None:
        return []
    out = []
    for q in k.quotes:
        text = page_text(q.doc, q.page)
        if text and normalize(q.quote) in normalize(text):
            out.append(q)
    return out


def block(k: Known, quotes: list[Quote], refs: dict[tuple[str, int], str]) -> str:
    lines = [f"{HEADER} — {k.title}:"]
    for q in quotes:
        ref = refs.get((q.doc, q.page))
        lines.append(f"- {q.label()}: «{q.quote}»" + (f" [{ref}]" if ref else ""))
    if k.conclusion:
        lines.append(f"Вывод: {k.conclusion} Основание — {k.basis}. {ADVICE}")
    else:  # правила заказчика нет — ни одно значение не выбираем
        lines.append(f"Какое значение верно для вашего двигателя, руководства не уточняют. {ADVICE}")
    return "\n".join(lines)


def for_model(k: Known, quotes: list[Quote]) -> dict[str, Any]:
    """То же — в результат поиска, чтобы ответ модели не спорил с выводом."""
    return {
        "title": k.title,
        "quotes": [{"manual": q.label(), "text": q.quote} for q in quotes],
        "conclusion": k.conclusion or "нет: ни одно значение не выбирай",
        "rule": "Не выбирай одну формулировку как бесспорную. Блок с цитатами и выводом вставит код — не повторяй их "
        "и не пиши свой «Вывод:»; дай прямой ответ по выводу (если он есть) и шаги.",
    }


# ---------- противоречие, которое заметила модель ----------

_MODEL_HEADER = re.compile(r"^\s*(?:[⚠*#>\-\s]*)противоречи[ея] в документации", re.I)
_QUOTE_REF = re.compile(r"«([^»]{12,})»[^\n]*?\[(R\d+)\]")


def check_model_blocks(text: str, source_text: Callable[[str], str | None]) -> tuple[str, list[str]]:
    """Блок «Противоречие в документации» от модели: каждая цитата «…» [R…] — на странице этой ссылки.
    Меньше двух подтверждённых цитат — блок (заголовок и его строки до пустой строки) убирается."""
    lines = text.split("\n")
    out: list[str] = []
    notes: list[str] = []
    i = 0
    while i < len(lines):
        if not _MODEL_HEADER.search(lines[i]) or lines[i].startswith(HEADER):
            out.append(lines[i])
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j].strip():
            j += 1
        blk = lines[i:j]
        good = 0
        for ln in blk:
            for quote, ref in _QUOTE_REF.findall(ln):
                src = source_text(ref)
                if src and normalize(quote) in normalize(src):
                    good += 1
        if good >= 2:
            out.extend(blk)
            if not any("уточн" in ln.lower() for ln in blk):
                out.append(ADVICE)
        else:
            notes.append("Противоречие не подтверждено цитатами со страниц — блок убран.")
        i = j
    return "\n".join(out), notes
