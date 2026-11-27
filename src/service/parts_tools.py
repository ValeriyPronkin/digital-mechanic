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
    r"(?:заменить|поменять)\s+на\s+нов|одноразов|повторно\s+(?:ставить|использ|устанавл)|"
    r"(?:ставить|использовать|устанавливать)\s+повторно|можно\s+ограниченно|разового\s+монтажа|каталожн|обозначени",
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


# Слова, которые узла не называют: по ним запись чужой строки таблицы («болты крепления форсунок») попадала к вопросу
# о другом узле («чем затянуть болты крышек шатуна») — #162, приёмка 27.11, класс (а).
_GENERIC = {"затянуть", "затяжка", "момент", "крепление", "крепить", "снять", "снимать", "установить", "ставить",
            "проверить", "проверять", "мерить", "измерить", "замерить", "откручивать", "открутить", "отвернуть",
            "выставить", "тянуть", "использовать", "повторно", "нельзя", "одноразовый", "разовый", "монтаж",
            "оснастка", "приспособа", "приспособ", "приспособление", "ключ", "щуп", "прибор", "съёмник", "съемник",
            "сколько", "какая", "каким", "размер", "нужно", "делать", "работа", "ремонт", "сборка", "разборка",
            "менять", "поменять", "заменять", "замена", "меняю", "запчасть", "деталь", "нужный", "снятие",
            "мой", "перебирать", "перебрать", "мотор", "ограниченно", "ограниченный", "раз"}  # fmt: skip
# крепёж — узел называет только вместе с деталью; без неё — лишь если и в названии записи
_FASTENER = {"болт", "гайка", "винт", "шпилька", "шайба"}


_CANON = {b: a for a, b in _SAME}  # «инжектор» → «форсунка»: синонимы — одно слово узла


def _canon(words: set[str]) -> set[str]:
    return {_CANON.get(w, w) for w in words}


def _local(r: Record) -> set[str]:
    """Слова самой записи — название, цитата, операция и раздел страницы; не окружение страницы (keywords)."""
    return _canon(set(tokenize(f"{r.name} {r.quote} {r.operation} {r.node}")))


def node_words(question: str) -> set[str]:
    """Слова вопроса, которые называют узел или операцию («шкив», «коленчатый», «вал»), без общих слов."""
    return _canon({w for w in tokenize(question) if w not in _STOP and len(w) >= 3} - _GENERIC - _FASTENER)


def find(
    engine: str,
    query: str,
    kinds: set[str] | None = None,
    pages: set[tuple[str, int]] | None = None,
    limit: int = 8,
) -> list[Record]:
    """Записи двигателя, у которых узел или операция вопроса есть в их собственной строке (название, цитата).
    Страница ответа (`pages`) — только порядок, не повод взять запись: со страницы таблицы моментов иначе шли ключи
    других узлов (#162). Вопрос без узла («что заменить на новое?») — одноразовые и заменяемые детали со страниц
    ответа. Одно и то же название с тем же размером — один раз."""
    from service import glossary

    text = " ".join([query, *glossary.expand(query)])  # цеховые слова → термины руководства («форсунка»)
    want = {w for w in tokenize(text) if w not in _STOP and len(w) >= 3}
    own = {w for w in tokenize(query) if w not in _STOP and len(w) >= 3}  # слова механика, без глоссария
    for a, b in _SAME:
        if a in want or b in want:
            want |= {a, b}
            if a in own or b in own:
                own |= {a, b}
    specific = _canon(want - _GENERIC - _FASTENER)
    own_specific = _canon(own - _GENERIC - _FASTENER)
    fasteners = want & _FASTENER
    scored: list[tuple[int, int, int, Record]] = []
    for n, r in enumerate(records(engine)):
        if kinds and r.kind not in kinds:
            continue
        on_page = bool(pages and (r.doc, r.page) in pages)
        local = _local(r)
        named = _canon(set(tokenize(r.name)))
        if specific:
            hit = len(specific & local)
            need = min(3, len(own_specific))  # все слова узла («шкив коленчатого вала»), не больше трёх
            if need and len(own_specific & local) < need:
                continue  # узел вопроса (словами механика) не назван в записи — не к месту
            if not need and not hit:
                continue
            if r.kind == "part" and r.source == "замена" and not (own_specific & named):
                continue  # «заменить жгут» на странице об инжекторах — не запчасть к форсунке
            if fasteners and (local & _FASTENER) and not (fasteners & local):
                continue  # спрашивали про болты, а строка — про гайки другого соединения
            score = hit + 2 * len(specific & named)
        elif fasteners:
            if not (fasteners & named):
                continue
            score = 1
        else:
            if not (on_page and r.kind == "part" and r.source in ("одноразовая", "замена")):
                continue
            score = 1
        once = int(r.source == "одноразовая" and "part" in (kinds or set()))  # «что заменить на новое»
        scored.append((int(on_page), score + once, -n, r))
    scored.sort(key=lambda t: (t[1], t[0], t[2]), reverse=True)
    seen: set[tuple[str, str, str]] = set()
    out = []
    for *_, r in scored:
        key = (r.kind, r.name.lower(), _norm_code(r.code))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _norm_code(code: str) -> str:
    """«S =5», «S=5», «Sвн=5» — один ключ (#162, класс (б))."""
    return re.sub(r"\s+", "", code.lower()).replace("sвн", "s")


# ---------- разметка ответа для /api/v2: запчасти и инструмент отдельным цветом (Валерий и Никита, 27.11) ----------

_VERB = re.compile(r"(?:ить|ать|ять|еть|уть|ться|тся|ется|ится)$", re.I)
_LANDMARK = re.compile(r"^(?:коленчат|распределительн)\w*\s+вал", re.I)
_NOT_NAME = re.compile(r"^(?:карточк|допуска|проверк|работ|ремонт|двигател)", re.I)


def _name_pattern(name: str) -> re.Pattern[str] | None:
    """Название в любом падеже: основа каждого слова («уплотнительн\\w* кольц\\w* инжектор\\w*»)."""
    words = [w for w in re.findall(r"[а-яёa-z]+", name.lower()) if len(w) >= 3]
    if not words or (len(words) == 1 and len(words[0]) < 3):
        return None
    stems = [re.escape(w[: max(3, len(w) - 2)] if len(w) > 4 else w) + r"\w*" for w in words]
    return re.compile(r"(?<![\wё])" + r"\s+".join(stems) + r"(?![\wё])", re.I)


def spans(engine: str, text: str, cited: dict[tuple[str, int], str] | None = None) -> list[dict[str, object]]:
    """Где в тексте ответа запчасти и инструмент из реестра двигателя: [{type, text, start, end, name, designation,
    page, ref}]. Обозначение или размер ищется дословно, название — по основам слов. Без пересечений: длинное
    совпадение важнее короткого. `cited` — {(doc, страница): метка S…} страниц ответа: ссылка ставится, если
    страница записи в ответе; иначе ref=None (страница записи — в page). Размечает сервер по реестру, не модель."""
    cited = cited or {}
    where: dict[str, set[tuple[str, int]]] = {}
    for r in records(engine):
        if r.code:
            where.setdefault(r.code.lower(), set()).add((r.doc, r.page))
    found: list[tuple[int, int, int, bool, Record]] = []
    for r in records(engine):
        words = r.name.lower().split()
        if any(_VERB.search(w) or _NOT_NAME.match(w) for w in words):
            continue  # «заменить», «допускается» — не деталь (обрывки разбора)
        pats: list[tuple[re.Pattern[str], bool]] = []
        key = re.fullmatch(r"S(вн)?\s*=\s*(\d+)", r.code or "", re.I)
        if key:  # размер ключа «S=6» — при любой длине, вместе со словом «ключ» перед ним («ключ S=6», web-2 27.11)
            inner = r"\s*вн" if key.group(1) else ""
            pats.append((re.compile(rf"(?:ключ\w*\s+(?:на\s+)?)?\(?\bS{inner}\s*=\s*{key.group(2)}(?!\d)", re.I), True))
        elif r.code and re.search(r"\d", r.code) and len(r.code) >= 4:
            pats.append((re.compile(r"(?<![\w.\-])" + re.escape(r.code) + r"(?![\w\-])", re.I), True))
        # запчасть по одному названию — только из двух слов и больше («уплотнительные кольца инжектора»): одно слово
        # («кольцо», «вал») встречается в ответе на каждом шагу и красило бы всё подряд
        # «коленчатый вал», «распределительный вал» — в ответе как ориентир («повернуть коленчатый вал»), не запчасть
        if r.kind == "tool" or (len(words) > 1 and not _LANDMARK.match(r.name)):
            if p := _name_pattern(r.name):
                pats.append((p, False))
        for p, by_code in pats:
            for m in p.finditer(text):
                found.append((m.start(), m.end(), int((r.doc, r.page) in cited), by_code, r))
    # длиннее — раньше; при равной длине — запись со страницы ответа, затем совпавшая обозначением
    found.sort(key=lambda x: (-(x[1] - x[0]), -x[2], -int(x[3]), x[0]))
    taken: list[tuple[int, int]] = []
    out: list[dict[str, object]] = []
    for start, end, on_page, by_code, r in found:
        if any(start < e and s < end for s, e in taken):
            continue
        taken.append((start, end))
        # страница записи — только если она в ответе или обозначение встречается в руководствах на одной странице
        # («S=13» — на десятках страниц, «24-Ф-74784.001» — на одной); иначе страница и обозначение могут быть чужими
        exact = bool(on_page or (by_code and len(where.get(r.code.lower(), ())) == 1))
        out.append({
            "type": r.kind,
            "text": text[start:end],
            "start": start,
            "end": end,
            "name": r.name,
            "designation": (r.code or None) if (exact or by_code) else None,
            "page": r.page if exact else None,
            "manual_id": r.doc if exact else None,
            "ref": cited.get((r.doc, r.page)),
        })  # fmt: skip
    return sorted(out, key=lambda s: int(s["start"]))  # type: ignore[call-overload]
