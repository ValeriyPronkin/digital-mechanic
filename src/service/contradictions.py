"""Противоречивые инструкции в руководствах одного двигателя (требование заказчика, 26.11).

Агент не выбирает одну формулировку как бесспорную: показывает все дословно с документом и страницей, отмечает
«Противоречие в документации» и даёт безопасное правило, выведенное из самих страниц (`safe_rule`). Отсылки
«к специалисту / производителю / главному механику» нет: механик сам специалист, решение — сейчас (ответы
организаторов 27.11: обе формулировки со страницами и безопасное правило; у заказчика своего правила нет).

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
RULE = "Безопасное правило:"  # строка правила под формулировками; по ней блок находит интерфейс v2
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
    # страница, которая отсылает к другому разделу: {"doc", "page", "text" — слова отсылки на странице, "section",
    # "to": [doc, page] — страница раздела, "also": [{"quote" — дословно с той страницы, "note" — к чему он}]}
    refers: dict[str, Any] | None = None
    appendix: tuple[tuple[str, int], ...] = ()  # страницы-приложения с моментами затяжки / зазорами


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
            refers=i.get("refers"),
            appendix=tuple((d, int(p)) for d, p in i.get("appendix", [])),
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
_ADVICE_DUP = re.compile(
    r"^\s*(?:\W\s*)?(?:для вашей модификации[^.]*?)?(?:уточните|обратитесь|проконсультируйтесь|свяжитесь)\s+"
    r"(?:\w+\s+)?(?:у|к|с)?\s*(?:специалист|производител|изготовител|завод|дилер|сервис|главн\w* механик)",
    re.I,
)
_MODEL_RULE = re.compile(r"^\s*(?:[*\-•]\s*)?\**(?:безопасное правило|вывод)\**\s*:", re.I)


def neutralize(k: Known, text: str) -> str:
    """Ответ модели рядом с блоком кода: строки, где модель выбрала одну формулировку по спорной теме, — вывод
    заказчика со ссылкой на блок; «противоречий нет», свой «Вывод:» и повтор совета — убрать."""
    out: list[str] = []
    for ln in text.split("\n"):
        if _NO_CONTRADICTION.search(ln) or _ADVICE_DUP.search(ln) or _MODEL_RULE.match(ln):
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


def block(k: Known, quotes: list[Quote], refs: dict[tuple[str, int], str], page_text: PageText | None = None) -> str:
    lines = [f"{HEADER} — {k.title}:"]
    for q in quotes:
        ref = refs.get((q.doc, q.page))
        lines.append(f"- {q.label()}: «{q.quote}»" + (f" [{ref}]" if ref else ""))
    # правило из данных (зазоры ЯМЗ-236: «на холодном» удовлетворяет обеим формулировкам) или выведенное из страниц;
    # основание из данных механику не показывается (своего правила у заказчика нет — ответ организаторов 27.11)
    lines.append(f"{RULE} {k.conclusion or safe_rule(k, quotes, page_text)}")
    return "\n".join(lines)


def for_model(k: Known, quotes: list[Quote], page_text: PageText | None = None) -> dict[str, Any]:
    """То же — в результат поиска, чтобы ответ модели не спорил с выводом."""
    return {
        "title": k.title,
        "quotes": [{"manual": q.label(), "text": q.quote} for q in quotes],
        "conclusion": k.conclusion or f"{RULE} {safe_rule(k, quotes, page_text)}",
        "rule": "Не выбирай одну формулировку как бесспорную. Блок с цитатами и правилом вставит код — не повторяй их "
        "и не пиши свой «Вывод:»; дай прямой ответ по этому правилу и шаги. Не отсылай к производителю, специалисту "
        "или главному механику.",
    }


# ---------- безопасное правило, выведенное из страниц (ответ организаторов 27.11) ----------

PageText = Callable[[str, int], str | None]
_NUM_RE = r"\d+(?:[.,]\d+)?"
_VALUE = re.compile(rf"(?:от\s+)?({_NUM_RE})\s*(?:(±)\s*({_NUM_RE})|(?:-|–|—|…|\.\.\.|до)\s*({_NUM_RE}))")
_UNIT = re.compile(r"\s*(н\s*[*·⋅.]?\s*м|кпа|мпа|мм)(?![а-яё])", re.I)
_MAIN_UNIT = {
    **dict.fromkeys(("нм", "н*м", "н·м", "н⋅м", "н.м"), "Н·м"),
    "кпа": "кПа",
    "мпа": "МПа",
    "мм": "мм",
}
_ALT = re.compile(r"\s*\(([^)]*)\)")


@dataclass(frozen=True)
class Value:
    """Первое значение формулировки: диапазон как он написан, основная единица (если указана) и скобки за ним."""

    text: str
    lo: float
    hi: float
    unit: str | None
    alt: str | None


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def first_value(quote: str) -> Value | None:
    m = _VALUE.search(quote)
    if m is None:
        return None
    a, pm, d, b = m.groups()
    lo, hi = (_f(a) - _f(d), _f(a) + _f(d)) if pm else (_f(a), _f(b))
    end = m.end()
    unit = None
    u = _UNIT.match(quote, end)
    if u:
        unit = _MAIN_UNIT.get(re.sub(r"\s", "", u.group(1).lower()))
        end = u.end()
    alt_m = _ALT.match(quote, end)
    alt = re.sub(r"\s|от|до|кгс|[*·⋅.]м", "", alt_m.group(1).lower()) if alt_m else None
    return Value(m.group(0).strip(), min(lo, hi), max(lo, hi), unit, alt)


def _where(items: list[tuple[str, str]]) -> str:
    """[(документ, страница-или-ссылка)] → «РК, стр. 41, 56» / «[R1], [R2]»: страницы одного документа — вместе."""
    groups: dict[str, list[str]] = {}
    for doc, page in items:
        groups.setdefault(doc, []).append(page)
    return "; ".join(f"{doc}, стр. {', '.join(p)}" if doc else ", ".join(p) for doc, p in groups.items())


def derive(
    items: list[tuple[str, str, str]],
    appendix: set[tuple[str, str]] | None = None,
) -> str:
    """Правило по значениям формулировок `[(текст, документ, страница)]` — по порядку ответа организаторов:
    значения совпадают в основной единице и расходятся только в пересчёте → они совпадают; диапазоны пересекаются →
    укладываться в оба, каждый диапазон целиком со своей страницей; иначе — значение приложения, при сомнении —
    дефектовка узла. Новых чисел (общих границ, пересчётов) правило не составляет."""
    vals = [(first_value(t), doc, page) for t, doc, page in items]
    if any(v is None for v, _, _ in vals) or len(vals) < 2:
        return _NO_RULE
    known = [(v, doc, page) for v, doc, page in vals if v is not None]
    units = {v.unit for v, _, _ in known if v.unit}
    if len(units) > 1:  # разные основные единицы — значения не сравнить
        return _NO_RULE
    unit = next(iter(units), None)
    ranges: dict[tuple[float, float], list[tuple[Value, str, str]]] = {}
    for v, doc, page in known:
        ranges.setdefault((v.lo, v.hi), []).append((v, doc, page))
    if len(ranges) == 1 and unit and len({v.alt for v, _, _ in known}) > 1:
        v = known[0][0]
        where = _where([(doc, page) for _, doc, page in known])
        return (f"в {unit} значения совпадают — {v.text} {unit} ({where}); расходится только пересчёт в скобках, "
                f"поэтому правило — значение в {unit}.")  # fmt: skip
    spans = list(ranges)
    if len(spans) > 1 and all(a[0] <= b[1] and b[0] <= a[1] for a in spans for b in spans):
        parts = [f"{grp[0][0].text} ({_where([(d, p) for _, d, p in grp])})" for grp in ranges.values()]
        return f"держите значение в пределах всех диапазонов сразу: {' и '.join(parts)}."
    if appendix:
        app = {(v.lo, v.hi) for v, doc, page in known if (doc, page) in appendix}
        if len(app) == 1:
            grp = ranges[next(iter(app))]
            where = _where([(d, p) for _, d, p in grp if (d, p) in appendix])
            return f"значение приложения — {grp[0][0].text} ({where}); при сомнении — дефектовка узла."
    return _NO_RULE


_NO_RULE = (
    "значения не совпадают и не пересекаются, а приложение спор не решает — до работы с узлом проведите его "
    "дефектовку и сверьте узел с описанием на страницах выше; наугад ни одно значение не применяйте."
)


def _short(doc: str) -> str:
    return _DOC_SHORT.get(doc.rsplit("-", 1)[-1], doc)


def safe_rule(k: Known, quotes: list[Quote], page_text: PageText | None = None) -> str:
    """Безопасное правило известного противоречия без правила заказчика. Первым — отсылка: страница отсылает к
    разделу — действует он, его словами и со страницей (слова отсылки сверяются со страницей). Затем `derive`."""
    r = k.refers
    if r and page_text is not None:
        src = page_text(r["doc"], int(r["page"]))
        to_doc, to_page = r["to"][0], int(r["to"][1])
        target = next((q for q in quotes if (q.doc, q.page) == (to_doc, to_page)), None)
        to_text = page_text(to_doc, to_page) or ""
        also = [a for a in r.get("also", []) if normalize(a["quote"]) in normalize(to_text)]
        if src and normalize(r["text"]) in normalize(src) and target is not None:
            rule = (f"{_short(r['doc'])}, стр. {r['page']} отсылает к разделу «{r['section']}» — действует он "
                    f"({_short(to_doc)}, стр. {to_page}): «{target.quote}»")  # fmt: skip
            if also:
                rule += "; " + "; ".join(f"«{a['quote']}» ({a['note']})" for a in also)
            tv = first_value(target.quote)
            same = [(q, v) for q in quotes if tv and (v := first_value(q.quote)) and (v.lo, v.hi) == (tv.lo, tv.hi)]
            if tv and tv.unit and len(same) > 1 and len({v.alt for _, v in same}) > 1:
                where = _where([(_short(q.doc), str(q.page)) for q, _ in same])
                rule += f". В {tv.unit} это значение совпадает ({where}); расходится только пересчёт в скобках"
            others = [(q, v) for q in quotes if (v := first_value(q.quote)) and (q, v) not in same]
            for q, v in others:  # значение, которое раздел не подтверждает, — названо целиком со своей страницей
                where = f"{_short(q.doc)}, стр. {q.page}"
                head = f"Приложение ({where}) даёт" if (q.doc, q.page) in k.appendix else f"На {where} —"
                rule += f". {head} {v.text}: при отсылке действует раздел"
            return rule + "."
    appendix = {(_short(d), str(p)) for d, p in k.appendix}
    return derive([(q.quote, _short(q.doc), str(q.page)) for q in quotes], appendix)


# ---------- противоречие, которое заметила модель ----------

_MODEL_HEADER = re.compile(r"^\s*(?:[⚠*#>\-\s]*)противоречи[ея] в документации", re.I)
_QUOTE_REF = re.compile(r"«([^»]{12,})»[^\n]*?\[(R\d+)\]")


# фраза, которая отсылает к блоку противоречия («противоречие, см. ниже»): без блока она — обрывок
_ANNOUNCE = re.compile(r"[^.!?\n]*противоречи\w*[^.!?\n]*(?:ниже|выше|см\.)[^.!?\n]*[.!?]?", re.I)


def drop_announcement(text: str) -> str:
    """Блока «Противоречие в документации» в ответе нет — убрать фразы, которые на него отсылают."""
    if HEADER in text or re.search(_MODEL_HEADER.pattern, text, re.I | re.M):
        return text
    out = _ANNOUNCE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", out)).strip()


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
        good: list[tuple[str, str]] = []
        for ln in blk:
            for quote, ref in _QUOTE_REF.findall(ln):
                src = source_text(ref)
                if src and normalize(quote) in normalize(src):
                    good.append((quote, ref))
        if len(good) >= 2:
            # совет «уточните у …» и своё правило модели — убрать; правило выводит код из подтверждённых цитат
            out.extend(ln for ln in blk if not _ADVICE_DUP.search(ln) and not _MODEL_RULE.match(ln))
            out.append(f"{RULE} {derive([(q, '', f'[{ref}]') for q, ref in good])}")
        else:
            notes.append("Противоречие не подтверждено цитатами со страниц — блок убран.")
        i = j
    return drop_announcement("\n".join(out)), notes
