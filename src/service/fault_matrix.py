"""Матрица «код неисправности × двигатель» по руководствам (issue #10, D-10).

`data/fault_matrix.json` — 14 кодов × 5 моделей. Каждый вывод в ячейке — дословная цитата со страницей PDF:
применимость узла (`applicable` + `basis`), страницы с проверкой/ремонтом, работы, запчасти, предупреждения.

Код, а не модель, решает:
- совместимость (правило 5): `applicable == "false"` — узла у двигателя нет, заявки нет;
- что агент может положить в заявку: только подтверждённая ячейка (`status == "confirmed"`).

Проверка ячейки (`verify_cell`): документ — этого двигателя, страница в 1..число страниц PDF, цитата есть на
странице. Не прошло — ссылка выбрасывается; не прошло основание применимости — ячейка `unknown`, а не догадка.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from service.manuals.catalog import DOCS_BY_ID, canonical_engine, documents_for_engine

MATRIX_PATH = Path(__file__).resolve().parents[2] / "data" / "fault_matrix.json"
APPLICABLE = ("true", "false", "unknown")
STATUSES = ("confirmed", "not_applicable", "silent", "unknown")

PageText = Callable[[str, int], str | None]  # (doc_id, page) → текст страницы или None, если её нет


@dataclass
class Ref:
    doc: str
    page: int
    quote: str
    what: str = ""  # для страниц: проверка / регулировка / ремонт / нормы / неисправности / устройство
    designation: str = ""  # запчасть: каталожное обозначение — стоит в самой цитате (строка перечня)
    tools: list[str] = field(default_factory=list)  # работа: инструмент, как его называет страница (дословно)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Ref:
        return cls(
            doc=str(d["doc"]),
            page=int(d["page"]),
            quote=str(d["quote"]),
            what=str(d.get("what", "")),
            designation=str(d.get("designation", "")),
            tools=[str(t) for t in d.get("tools") or []],
        )

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"doc": self.doc, "page": self.page, "quote": self.quote}
        if self.what:
            out["what"] = self.what
        if self.designation:
            out["designation"] = self.designation
        if self.tools:
            out["tools"] = list(self.tools)
        return out

    @property
    def part_name(self) -> str:
        """Запчасть без обозначения (обозначение — в конце цитаты строки перечня)."""
        return self.quote.replace(self.designation, "").strip(" .,;") if self.designation else self.quote


@dataclass
class Cell:
    code: str
    engine: str
    applicable: str  # true / false / unknown
    basis: Ref | None  # на чём основана применимость
    why: str = ""  # для false — почему узла нет (показываем механику)
    inference: bool = False  # вывод из полной теххарактеристики (узла в ней нет), а не прямая фраза
    note: str = ""
    pages: list[Ref] = field(default_factory=list)
    operations: list[Ref] = field(default_factory=list)  # quote — сама работа
    spare_parts: list[Ref] = field(default_factory=list)  # quote — название запчасти
    safety: list[Ref] = field(default_factory=list)
    status: str = "unknown"

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Cell:
        def refs(key: str) -> list[Ref]:
            return [Ref.from_json(x) for x in d.get(key) or []]

        return cls(
            code=str(d["code"]),
            engine=str(d["engine"]),
            applicable=str(d["applicable"]),
            basis=Ref.from_json(d["basis"]) if d.get("basis") else None,
            why=str(d.get("why", "")),
            inference=bool(d.get("inference", False)),
            note=str(d.get("note", "")),
            pages=refs("pages"),
            operations=refs("operations"),
            spare_parts=refs("spare_parts"),
            safety=refs("safety"),
            status=str(d.get("status", "unknown")),
        )

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "engine": self.engine,
            "status": self.status,
            "applicable": self.applicable,
            "basis": self.basis.to_json() if self.basis else None,
        }
        for key in ("why", "note"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        if self.inference:
            out["inference"] = True
        for key in ("pages", "operations", "spare_parts", "safety"):
            out[key] = [r.to_json() for r in getattr(self, key)]
        return out

    def refs(self) -> list[Ref]:
        return [*([self.basis] if self.basis else []), *self.pages, *self.operations, *self.spare_parts, *self.safety]


def status_of(cell: Cell) -> str:
    if cell.applicable == "false":
        return "not_applicable"
    if cell.applicable == "unknown":
        return "unknown"
    return "confirmed" if cell.pages and cell.operations else "silent"


_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Для сравнения цитаты со страницей: регистр, ё, разделители ячеек таблиц и пробелы не важны."""
    return _WS.sub(" ", text.lower().replace("ё", "е").replace("|", " ").replace("­", "")).strip()


def ref_problem(ref: Ref, engine: str, page_text: PageText | None) -> str | None:
    """Почему ссылка недействительна, или None. Без page_text проверяются документ и номер страницы."""
    doc = DOCS_BY_ID.get(ref.doc)
    if doc is None:
        return f"нет документа {ref.doc}"
    if doc not in documents_for_engine(engine):
        return f"{ref.doc} — руководство другого двигателя"
    if not 1 <= ref.page <= doc.pages:
        return f"{ref.doc}: страницы {ref.page} нет (в PDF {doc.pages})"
    if not ref.quote.strip():
        return "пустая цитата"
    if ref.designation and normalize(ref.designation) not in normalize(ref.quote):
        return f"{ref.doc}:{ref.page}: обозначения {ref.designation} нет в цитате"
    if page_text is not None:
        text = page_text(ref.doc, ref.page)
        if text is None or normalize(ref.quote) not in normalize(text):
            return f"{ref.doc}:{ref.page}: цитаты нет на странице"
        page = normalize(text)
        missing = [t for t in ref.tools if normalize(t) not in page]
        if missing:
            return f"{ref.doc}:{ref.page}: инструмента нет на странице: {', '.join(missing)}"
    return None


def verify_cell(cell: Cell, page_text: PageText | None = None) -> tuple[Cell, list[str]]:
    """Ячейка без недействительных ссылок и с пересчитанным статусом + список выброшенного."""
    problems: list[str] = []

    def keep(refs: list[Ref], kind: str) -> list[Ref]:
        ok = []
        for r in refs:
            p = ref_problem(r, cell.engine, page_text)
            if p:
                problems.append(f"{kind}: {p}")
            else:
                ok.append(r)
        return ok

    applicable, basis = cell.applicable, cell.basis
    if applicable not in APPLICABLE:
        problems.append(f"applicable={applicable!r}")
        applicable, basis = "unknown", None
    elif basis is not None and (p := ref_problem(basis, cell.engine, page_text)):
        problems.append(f"основание: {p}")
        applicable, basis = "unknown", None
    elif applicable != "unknown" and basis is None:
        problems.append("вывод о применимости без основания")
        applicable = "unknown"
    out = Cell(
        code=cell.code,
        engine=cell.engine,
        applicable=applicable,
        basis=basis,
        why=cell.why if applicable == "false" else "",
        inference=cell.inference and applicable == "false",
        note=cell.note,
        pages=keep(cell.pages, "страница") if applicable != "false" else [],
        operations=keep(cell.operations, "работа") if applicable != "false" else [],
        spare_parts=keep(cell.spare_parts, "запчасть") if applicable != "false" else [],
        safety=keep(cell.safety, "безопасность") if applicable != "false" else [],
    )
    out.status = status_of(out)
    return out, problems


# ---------- загрузка для сервиса ----------


@lru_cache(maxsize=1)
def _load(path: Path = MATRIX_PATH) -> dict[tuple[str, str], Cell]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cells: dict[tuple[str, str], Cell] = {}
    for d in data["cells"]:
        # При загрузке — проверка без текста страниц: документ этого двигателя и номер страницы.
        # Цитаты сверяются при сборке и тестом на индексе.
        cell, _ = verify_cell(Cell.from_json(d))
        cells[(cell.code, cell.engine)] = cell
    return cells


def all_cells() -> list[Cell]:
    return list(_load().values())


def cell_for(code: str, engine: str) -> Cell | None:
    canon = canonical_engine(engine)
    if canon is None:
        return None
    return _load().get((code, canon))


def card_explanation(code: str, engine: str) -> dict[str, Any] | None:
    """Пояснение к карточке отклонения из матрицы — без модели, 0 токенов (issue #16).

    Подтверждённая ячейка — работы и предупреждения со ссылками на страницы; «молчит» / «не ясно» — указание
    на дефектовку. Узла нет — None: карточка и так говорит «повторите проверку».
    """
    cell = cell_for(code, engine)
    if cell is None or cell.status == "not_applicable":
        return None

    def ref(r: Ref) -> dict[str, Any]:
        doc = DOCS_BY_ID[r.doc]
        url = f"/manuals/{r.doc}#page={r.page}"
        out: dict[str, Any] = {"text": r.quote, "manual": doc.designation, "pdf_page": r.page, "url": url}
        if r.what:
            out["what"] = r.what
        if r.tools:
            out["tools"] = list(r.tools)
        return out

    if cell.status != "confirmed":
        note = "В руководстве этого двигателя нет порядка работ по этому узлу — нужна дефектовка."
        return {"status": cell.status, "steps": [], "safety": [], "pages": [], "note": note}
    return {
        "status": "confirmed",
        "pages": [ref(p) for p in cell.pages],
        "steps": [ref(o) for o in cell.operations],
        "safety": [ref(x) for x in cell.safety],
        "parts": [
            {**ref(p), "text": p.part_name, "designation": p.designation} for p in cell.spare_parts if p.designation
        ],
        "note": cell.note,
    }
