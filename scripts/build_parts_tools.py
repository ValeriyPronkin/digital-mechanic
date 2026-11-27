"""Реестр запчастей и инструмента по руководствам каждого двигателя → data/parts_tools.json (ночь 27→28.11).

Производные данные, не текст руководств: у записи — название, обозначение или размер, страница, узел или операция и
короткая дословная цитата (не больше 20 слов подряд, #96) — по ней тест сверяет запись со страницей индекса.
Источники на страницах руководств ЭТОГО двигателя (D-29: только дословно, не догадываемся):
  запчасть с обозначением — строка перечня «Название Обозначение» (`matrix_enrich.table_rows`);
  запчасть к замене — «заменить … новыми», «установить новые …», «одноразового использования»;
  инструмент — упоминание в работе (`matrix_enrich.TOOL`: щуп с размером, ключ S=…, съёмник, оправка, манометр…);
  специальное приспособление с обозначением — «приспособление 16-У-236817», «съёмник И-801».

  uv run python scripts/build_parts_tools.py      → data/parts_tools.json и reports/parts-tools-registry.md
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from matrix_enrich import TOOL, flat, table_rows
from service.fault_matrix import normalize
from service.manuals.catalog import ENGINES, documents_for_engine
from service.manuals.index import index_dir, load_fragments
from service.manuals.lexical import tokenize

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "parts_tools.json"
REPORT = ROOT / "reports" / "parts-tools-registry.md"
QUOTE_WORDS = 20

_WORD = re.compile(r"\S+")
_SENT = re.compile(r"(?<=[.;!?])\s+|\n")
SPECIAL = re.compile(
    r"(?P<name>приспособлени\w*|съ[её]мник\w*|оправк\w*|шаблон\w*|ключ\w*|головк\w*)[^.\n]{0,30}?"
    r"(?P<des>\b\d{2}-[А-ЯA-Z]-\d{4,6}(?:\.\d{3})?|\bИ-?\d{3,4}[\w.\-]*)",
    re.I,
)
_REPLACE = re.compile(
    r"(?:заменить|замените|заменяют|заменяйте|установить\s+нов\w+|устанавливать\s+нов\w+|ставить\s+нов\w+)\s+"
    r"(?:на\s+нов\w+\s+)?(?P<a>[^.,;:()\n]{4,60})"
    r"|(?P<c>[а-яё]{4,}(?:\s+[а-яё]+){0,3})\s*[-–—,]?\s*(?:одноразов\w+|повторно(?:е)?\s+(?:не\s+)?(?:использ|применя)\w*)",
    re.I,
)
_PART_STOP = re.compile(
    r"^(?:на|при|в|во|и|или|с|со|по|для|после|если|из|до|от|у|к|а|но|затем|при|новы\w*|нов\w+|его|её|ее|их|"
    r"необходимости|станции|сто)$",
    re.I,
)
_ADJ = re.compile(r"(?:ый|ий|ой|ая|яя|ое|ее|ые|ие|ую|юю|ого|его|ых|их)$", re.I)
_NOT_A_PART = re.compile(
    r"^(?:масло|жидкост|топлив|смазк|воду|вода|деталь|детали|узел|узлы|агрегат|сборочн|комплект|элемент$|"
    r"прибор$|отремонт|восстанов|выправ)",
    re.I,
)
_VERB = re.compile(r"(?:ить|ать|ять|еть|уть)$", re.I)  # «заменить» — обрывок разбора, не деталь
_WORN = re.compile(r"^(?:неисправн|поврежд|изношен|вышедш|деформирован|данн|эти|этот|эту)\w*$", re.I)
# специальный инструмент ЗМЗ в перечне: «ЗМ 7853-4418 – Оправка для …», «6999-7679 Съемник подшипника …»
SPECIAL_ROW = re.compile(
    r"(?P<des>(?:ЗМ\s?)?\d{4}-\d{4}|\d{2}-[А-ЯЁ]-\d{4,6}(?:\.\d{3})?)\s*[–—-]?\s*"
    r"(?P<name>Оправк\w*|Съ[её]мник\w*|Приспособлени\w*|Ключ\w*|Головк\w*|Шаблон\w*|Переходник\w*|Державк\w*|"
    r"Втулк\w*\s+монтажн\w*|Рукоятк\w*|Стержень|Сектор\w*|Кондуктор\w*|Индикатор\w*|Щуп\w*)",
)
# «Уплотнительные кольца инжектора (6) и бокового штуцера (7), упорная шайба (8) инжектора одноразового использования»
ONE_TIME = re.compile(r"одноразов\w*\s+(?:использ|примен)\w*|повторно\s+не\s+(?:использ|применя|устанавл)\w*", re.I)

_TOOL_BASE = {
    "щуп": "щуп",
    "динамометрическ": "динамометрический ключ",
    "ключ": "ключ",
    "s": "ключ",
    "торцев": "торцевая головка",
    "съем": "съёмник",
    "съём": "съёмник",
    "приспособлен": "приспособление",
    "оправк": "оправка",
    "манометр": "манометр",
    "индикатор": "индикатор",
    "микрометр": "микрометр",
    "нутромер": "нутромер",
    "штангенциркул": "штангенциркуль",
    "угломер": "угломер",
    "компрессометр": "компрессометр",
    "стробоскоп": "стробоскоп",
    "мультиметр": "мультиметр",
    "диагностическ": "диагностический прибор",
    "отв": "отвёртка",
    "плоскогубц": "плоскогубцы",
    "линейк": "линейка",
    "переходник": "переходник",
    "державк": "державка",
    "рукоятк": "рукоятка",
    "сектор": "сектор",
    "шаблон": "шаблон",
    "головк": "головка",
    "втулк": "монтажная втулка",
    "стерж": "стержень",
    "кондуктор": "кондуктор",
}


def tool_name(match: str) -> str:
    """Название инструмента по упоминанию: «щупом 0,25 мм» → «щуп», «(S=22)» → «ключ»."""
    low = match.lower().strip(" ()")
    for stem, name in _TOOL_BASE.items():
        if low.startswith(stem):
            return name
    return low.split()[0]


def window(sentence: str, start: int, end: int, words: int = QUOTE_WORDS) -> str:
    """Дословный отрывок фразы вокруг [start, end) — не длиннее `words` слов подряд (#96)."""
    toks = list(_WORD.finditer(sentence))
    if len(toks) <= words:
        return sentence.strip()
    hit = next((i for i, t in enumerate(toks) if t.end() > start), 0)
    last = next((i for i, t in enumerate(toks) if t.end() >= end), hit)
    lo = max(0, min(hit - (words - (last - hit + 1)) // 2, len(toks) - words))
    hi = min(len(toks), lo + words)
    return sentence[toks[lo].start() : toks[hi - 1].end()].strip()


_KW_STOP = {"который", "которые", "должен", "должна", "должны", "необходимо", "следует", "после", "перед", "через",
            "между", "также", "только", "можно", "нужно", "этого", "своей", "своих", "более", "менее", "страница",
            "руководство", "двигатель", "двигатели", "двигателей"}  # fmt: skip


def keywords(text: str, at: int, span: int = 350, limit: int = 12) -> list[str]:
    """Леммы окружения упоминания (±span знаков): тема записи для поиска — не текст руководства, а набор слов."""
    seen: dict[str, None] = {}
    for w in tokenize(text[max(0, at - span) : at + span]):
        if len(w) >= 5 and not w[0].isdigit() and w not in _KW_STOP:
            seen.setdefault(w, None)
    return list(seen)[:limit]


def page_texts() -> tuple[dict[tuple[str, int], str], dict[tuple[str, int], str]]:
    pages: dict[tuple[str, int], list[str]] = defaultdict(list)
    sections: dict[tuple[str, int], str] = {}
    for f in load_fragments(index_dir() / "fragments.jsonl"):
        pages[(f.doc_id, f.page)].append(f.text)
        if f.section and (f.doc_id, f.page) not in sections:
            sections[(f.doc_id, f.page)] = f.section.strip()
    return {k: "\n".join(v) for k, v in pages.items()}, sections


def _part_name(raw: str) -> str:
    """Название детали: слова до предлога или союза, не больше четырёх; последнее — не прилагательное."""
    words: list[str] = []
    for w in raw.lower().split():
        w = w.strip("«»\"'")
        if not re.fullmatch(r"[а-яё\-]+", w) or _PART_STOP.match(w):
            if words:
                break
            continue
        words.append(w)
        if len(words) >= 4 or (len(words) >= 1 and not _ADJ.search(w)):
            break
    while words and _WORN.match(words[0]):
        words = words[1:]  # «неисправный датчик» → «датчик»: состояние — не название
    if not words or _ADJ.search(words[-1]) or _NOT_A_PART.match(" ".join(words)) or _VERB.search(words[-1]):
        return ""
    return " ".join(words)


Pages = dict[tuple[str, int], str]


def build_engine(engine: str, pages: Pages, sections: Pages) -> dict[str, Any]:
    docs = {d.doc_id for d in documents_for_engine(engine)}
    parts: dict[tuple[Any, ...], dict[str, Any]] = {}
    tools: dict[tuple[Any, ...], dict[str, Any]] = {}
    for (doc, page), text in sorted(pages.items()):
        if doc not in docs:
            continue
        node = sections.get((doc, page), "")
        page_norm = normalize(text)
        for name, des in table_rows(text):
            quote = f"{name} {des}"
            if normalize(quote) in page_norm:
                parts.setdefault(("des", des), {"name": name, "designation": des, "doc": doc, "page": page,
                                                "node": node, "source": "перечень", "quote": quote})  # fmt: skip
        # перечень одноразовых деталей бывает на двух строках — фразы страницы целиком
        joined = re.sub(r"\n(?=[а-яё(])", " ", flat(text))  # строка со строчной — продолжение фразы
        for sent in re.split(r"(?<=[.!?])\s+|\n", joined):
            one = ONE_TIME.search(sent)
            if one:
                head = re.sub(r"\(\s*\d+\s*\)", " ", sent[: one.start()])
                for item in re.split(r",|\s+и\s+", head):
                    words = [w for w in re.findall(r"[А-Яа-яЁё\-]+", item) if not _PART_STOP.match(w)]
                    name = " ".join(words[:4]).lower()
                    if len(name) < 4 or _NOT_A_PART.match(name) or name.startswith(("данн", "эти")):
                        continue
                    quote = window(sent, 0, one.end())
                    key = ("rep", doc, page, name)
                    if key not in parts and normalize(quote) in page_norm:
                        parts[key] = {"name": name, "designation": "", "doc": doc, "page": page, "node": node,
                                      "source": "одноразовая", "quote": quote}  # fmt: skip
        for line in flat(text).split("\n"):
            for sent in _SENT.split(line):
                if len(sent) < 8:
                    continue
                for m in _REPLACE.finditer(sent):
                    raw = m.group("a") or m.group("c") or ""
                    name = _part_name(raw)
                    if len(name) < 4:
                        continue
                    quote = window(sent, m.start(), m.end())
                    key = ("rep", doc, page, name)
                    if key not in parts and normalize(quote) in page_norm:
                        parts[key] = {"name": name, "designation": "", "doc": doc, "page": page, "node": node,
                                      "source": "замена", "quote": quote}  # fmt: skip
                for m in SPECIAL_ROW.finditer(sent):
                    quote = window(sent, m.start(), m.end())
                    key = ("spec", doc, page, m.group("des"))
                    if key not in tools and normalize(quote) in page_norm:
                        tools[key] = {"name": tool_name(m.group("name")), "size": m.group("des"), "doc": doc,
                                      "page": page, "operation": quote, "node": node, "quote": quote}  # fmt: skip
                for m in SPECIAL.finditer(sent):
                    quote = window(sent, m.start(), m.end())
                    key = ("spec", doc, page, m.group("des"))
                    if key not in tools and normalize(quote) in page_norm:
                        tools[key] = {"name": tool_name(m.group("name")), "size": m.group("des"), "doc": doc,
                                      "page": page, "operation": quote, "node": node, "quote": quote}  # fmt: skip
                for m in TOOL.finditer(sent):
                    mention = m.group(0).strip(" ()")
                    name = tool_name(mention)
                    size = mention if re.search(r"\d", mention) else ""
                    if name in ("приспособление", "съёмник") and (d := re.search(r"(?:И-?|\d)[\w.\-]*\d$", size)):
                        size = d.group(0)  # «приспособления 5340.3901010» → «5340.3901010»
                    if name == "ключ" and not size:
                        continue  # «ключ» без размера — не инструмент работы («ключ зажигания»)
                    quote = window(sent, m.start(), m.end())
                    tkey = ("tool", doc, page, name, size.lower())
                    if tkey not in tools and normalize(quote) in page_norm:
                        tools[tkey] = {"name": name, "size": size, "doc": doc, "page": page, "operation": quote,
                                      "node": node, "quote": quote}  # fmt: skip
    for rec in [*parts.values(), *tools.values()]:
        text = re.sub(r"\s+", " ", flat(pages[(rec["doc"], rec["page"])]))
        at = text.find(re.sub(r"\s+", " ", rec["quote"])[:24])
        rec["keywords"] = keywords(text, max(at, 0)) if at >= 0 else keywords(text, 0, span=10**6)
    return {"parts": list(parts.values()), "tools": list(tools.values())}


def dump(data: dict[str, Any]) -> str:
    """JSON с записью на строку: файл короче, а diff пересборки читается по записям."""
    out = ["{", f' "_comment": {json.dumps(data["_comment"], ensure_ascii=False)},', ' "engines": {']
    engines = list(data["engines"].items())
    for i, (engine, d) in enumerate(engines):
        out.append(f"  {json.dumps(engine, ensure_ascii=False)}: {{")
        for j, kind in enumerate(("parts", "tools")):
            rows = [f"    {json.dumps(r, ensure_ascii=False)}" for r in d[kind]]
            out.append(f'   "{kind}": [')
            out.append(",\n".join(rows))
            out.append("   ]" + ("," if j == 0 else ""))
        out.append("  }" + ("," if i < len(engines) - 1 else ""))
    out += [" }", "}"]
    return "\n".join(out) + "\n"


def main() -> None:
    pages, sections = page_texts()
    engines = {e: build_engine(e, pages, sections) for e in ENGINES}
    data = {
        "_comment": (
            "Реестр запчастей и инструмента по руководствам двигателя (scripts/build_parts_tools.py). Производные "
            "данные: название, обозначение или размер, страница PDF, узел или операция; quote — дословный отрывок "
            "не длиннее 20 слов, по нему запись сверяется со страницей (tests/test_parts_tools_registry.py)."
        ),
        "engines": engines,
    }
    OUT.write_text(dump(data), encoding="utf-8")
    lines = ["# Реестр запчастей и инструмента (data/parts_tools.json)", "",
             "| Двигатель | запчастей с обозначением | запчастей к замене | инструмента |",
             "|---|---|---|---|"]  # fmt: skip
    for e, d in engines.items():
        des = sum(1 for p in d["parts"] if p["designation"])
        lines.append(f"| {e} | {des} | {len(d['parts']) - des} | {len(d['tools'])} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
