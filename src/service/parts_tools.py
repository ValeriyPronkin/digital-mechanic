"""Реестр запчастей и инструмента по руководствам двигателя (`data/parts_tools.json`, ночь 27→28.11; D-29, D-46).

Запись — название, обозначение (запчасть) или размер (инструмент), страница PDF, узел или операция и короткая
дословная цитата, по которой она сверена со страницей. Собирает `scripts/build_parts_tools.py`. Здесь — поиск:
по словам вопроса (леммы) и по страницам ответа. Ответ «какой инструмент / какие запчасти» строит код из этих
записей, а не модель; обозначения — только как в руководстве этого двигателя.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from service.manuals.catalog import canonical_engine
from service.manuals.lexical import tokenize

PATH = Path(__file__).resolve().parents[2] / "data" / "parts_tools.json"

TOOL_ASK = re.compile(
    r"инструмент|приспособлен|оснастк|чем\s+(?:мерить|измер|замер|откруч|отвернуть|снять|снимать|проверить|"
    r"проверять|выставить|затянуть|тянуть)|каким\s+(?:ключ|щуп|прибор)|какой\s+(?:ключ|щуп|съ[её]мник)|"
    r"(?:ключ|головк)\w*\s+на\s+сколько|приспособа",
    re.I,
)
PART_ASK = re.compile(
    r"запчаст|запасн\w+\s+част|какие\s+(?:нужны\s+)?детал|что\s+(?:заменить|поменять|менять|ставить)\s+(?:на\s+)?нов|"
    r"(?:заменить|поменять)\s+на\s+нов|одноразов|повторно\s+(?:ставить|использ)|каталожн|обозначени",
    re.I,
)
_STOP = {"какой", "какие", "нужный", "нужен", "нужно", "нужны", "инструмент", "запчасть", "деталь", "что", "для",
         "чем", "этот", "двигатель", "можно", "надо", "новый", "заменить", "мой", "наш", "при", "как"}  # fmt: skip


# одно и то же в разных руководствах: у ЯМЗ-536 «инжектор», у механика и в РЭ — «форсунка»
_SAME = (("форсунка", "инжектор"), ("шкив", "ступица"), ("головка", "гбц"))


@dataclass(frozen=True)
class Record:
    kind: str  # "part" | "tool"
    name: str
    code: str  # обозначение запчасти или размер / обозначение инструмента; пусто — не указано
    doc: str
    page: int
    node: str
    operation: str
    quote: str
    source: str = ""
    keywords: tuple[str, ...] = ()

    def label(self) -> str:
        """Как назвать механику: «щупом 0,25 мм», «ключ S=13», «втулка коромысла 236-1007118»."""
        if self.kind == "part":
            name = self.name[:1].lower() + self.name[1:] if self.name[1:2].islower() else self.name
            return f"{name} {self.code}".strip() if self.code and self.code not in self.name else name
        if self.code and self.code.lower().startswith(self.name[:4].lower()):
            return self.code  # «щупом 0,25 мм» — уже с названием
        return f"{self.name} {self.code}".strip()

    def words(self) -> set[str]:
        return set(tokenize(f"{self.name} {self.node} {self.operation}")) | set(self.keywords)


@lru_cache(maxsize=1)
def _load() -> dict[str, tuple[Record, ...]]:
    if not PATH.exists():
        return {}
    data = json.loads(PATH.read_text(encoding="utf-8"))
    out: dict[str, tuple[Record, ...]] = {}
    for engine, d in data.get("engines", {}).items():
        recs = [Record("part", p["name"], p.get("designation", ""), p["doc"], int(p["page"]), p.get("node", ""),
                       p.get("quote", ""), p["quote"], p.get("source", ""), tuple(p.get("keywords", [])))
                for p in d.get("parts", [])]  # fmt: skip
        recs += [Record("tool", t["name"], t.get("size", ""), t["doc"], int(t["page"]), t.get("node", ""),
                        t.get("operation", ""), t["quote"], "", tuple(t.get("keywords", [])))
                 for t in d.get("tools", [])]  # fmt: skip
        out[engine] = tuple(recs)
    return out


def records(engine: str) -> tuple[Record, ...]:
    return _load().get(canonical_engine(engine) or engine, ())


def asks(question: str) -> set[str]:
    """Что спрашивает механик: {"tool"}, {"part"}, оба или ничего."""
    kinds = set()
    if TOOL_ASK.search(question):
        kinds.add("tool")
    if PART_ASK.search(question):
        kinds.add("part")
    return kinds


def find(
    engine: str,
    query: str,
    kinds: set[str] | None = None,
    pages: set[tuple[str, int]] | None = None,
    limit: int = 8,
) -> list[Record]:
    """Записи двигателя по словам запроса и (или) со страниц `pages`. Порядок: страница ответа, затем больше
    общих слов; одно и то же название с тем же размером — один раз."""
    from service import glossary

    text = " ".join([query, *glossary.expand(query)])  # цеховые слова → термины руководства («форсунка»)
    want = {w for w in tokenize(text) if w not in _STOP and len(w) >= 3}
    for a, b in _SAME:
        if a in want or b in want:
            want |= {a, b}
    scored: list[tuple[int, int, int, Record]] = []
    for n, r in enumerate(records(engine)):
        if kinds and r.kind not in kinds:
            continue
        on_page = bool(pages and (r.doc, r.page) in pages)
        hit = len(want & r.words())
        named = len(want & set(tokenize(r.name)))  # слово вопроса в самом названии — сильнее слов окружения
        if not on_page and (not hit or (not named and hit < min(2, len(want)))):
            continue
        hit += 2 * named
        once = int(r.source == "одноразовая" and "part" in (kinds or set()))  # «что заменить на новое»
        scored.append((int(on_page), hit + once, -n, r))
    scored.sort(reverse=True)
    seen: set[tuple[str, str, str]] = set()
    out = []
    for *_, r in scored:
        key = (r.kind, r.name.lower(), r.code.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out
