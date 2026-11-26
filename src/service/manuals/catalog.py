"""Каталог руководств заказчика и карта «модель двигателя из карточки ТС → документы».

Карта — единственный источник правды для жёсткого фильтра поиска (правило 3 в CLAUDE.md):
поиск сначала оставляет только документы двигателя ТС и лишь потом ранжирует.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KIND_OPERATION = "эксплуатация"
KIND_REPAIR = "ремонт"


@dataclass(frozen=True)
class Document:
    doc_id: str  # стабильный идентификатор: им ссылаемся в заявке (references[].manual)
    file: str  # имя PDF в MANUALS_DIR
    designation: str  # обозначение для механика
    engines: tuple[str, ...]  # канонические модели двигателей (как в data/vehicles.json)
    kind: str  # вид по умолчанию: эксплуатация / ремонт
    pages: int = 0  # страниц в PDF (паспорт индекса): ссылка на страницу вне 1..pages невозможна
    toc_pages: tuple[int, ...] = ()  # страницы PDF (с 1) с оглавлением
    repair_from_page: int | None = None  # для общих РЭ+ремонт: с этой страницы PDF — «ремонт»
    section_from_page_title: bool = False  # раздел = заголовок модуля данных в первой строке страницы

    def kind_of_page(self, page: int) -> str:
        if self.repair_from_page is not None and page >= self.repair_from_page:
            return KIND_REPAIR
        return self.kind


DOCUMENTS: tuple[Document, ...] = (
    Document(
        doc_id="yamz-236-re",
        file="ЯМЗ_236_руководство по эксплуатации.pdf",
        designation="ЯМЗ-236М2, ЯМЗ-238М2. Руководство по эксплуатации 236-3902150-Б РЭ",
        engines=("ЯМЗ-236М2",),
        kind=KIND_OPERATION,
        pages=172,
        toc_pages=(170, 171, 172),
    ),
    Document(
        doc_id="yamz-236-rk",
        file="ЯМЗ_236_руководство по РЕМОНТУ.pdf",
        designation="ЯМЗ-236, ЯМЗ-238. Руководство по ремонту",
        engines=("ЯМЗ-236М2",),
        kind=KIND_REPAIR,
        pages=287,
        toc_pages=(2, 3, 4, 5, 6, 7),
    ),
    Document(
        doc_id="yamz-536-re",
        file="yamz-536_re_2016.pdf",
        designation="ЯМЗ-536. Руководство по эксплуатации 536.3902150 РЭ",
        engines=("ЯМЗ-536",),
        kind=KIND_OPERATION,
        pages=285,
        toc_pages=(282, 283, 284, 285),
    ),
    Document(
        doc_id="yamz-536-rk",
        file="yamz-536_rk_2013.pdf",
        designation="ЯМЗ-536. Руководство по ремонту 536.01.02 РК",
        engines=("ЯМЗ-536",),
        kind=KIND_REPAIR,
        pages=603,
        section_from_page_title=True,
    ),
    Document(
        doc_id="zmz-5234-rk",
        file="zmz-5234_rk_2025.pdf",
        designation="ЗМЗ-5234.10. Руководство по ремонту (изд. 5, 2025)",
        engines=("ЗМЗ-5234.10",),
        kind=KIND_REPAIR,
        pages=158,
        toc_pages=(135, 136),
    ),
    Document(
        doc_id="zmz-409-rk",
        file="zmz-40904-40905_rk_2025.pdf",
        designation="ЗМЗ-40904.10, ЗМЗ-40905.10. Руководство по эксплуатации, ТО и ремонту (изд. 10, 2025)",
        engines=("ЗМЗ-40904.10", "ЗМЗ-40905.10"),
        kind=KIND_OPERATION,
        pages=238,
        toc_pages=(3, 4),
        repair_from_page=112,
    ),
)

DOCS_BY_ID: dict[str, Document] = {d.doc_id: d for d in DOCUMENTS}
ENGINES: tuple[str, ...] = tuple(sorted({e for d in DOCUMENTS for e in d.engines}))

# Латиница, похожая на кириллицу, в обозначениях моделей (ввод с клавиатуры, OCR)
_LOOKALIKE = str.maketrans({"M": "М", "Z": "З", "A": "А", "E": "Е", "K": "К", "H": "Н", "O": "О", "P": "Р"})
_SPACES = re.compile(r"[\s–—_]+")
_SUFFIX = re.compile(r"\.\d+|М\d*")


def _norm(name: str) -> str:
    s = _SPACES.sub("-", name.strip().upper().translate(_LOOKALIKE))
    s = s.replace("ЯМ3", "ЯМЗ").replace("3МЗ", "ЗМЗ")
    return re.sub(r"-+", "-", s)


def canonical_engine(name: str) -> str | None:
    """Модель из карточки ТС или ввода механика → каноническое имя; None — двигатель неизвестен.

    Допускает «ЗМЗ-5234» без «.10» и латинские двойники букв. Неоднозначный ввод
    (например, «ЗМЗ-409») не угадывается: None.
    """
    n = _norm(name)
    if not n:
        return None
    exact = [e for e in ENGINES if _norm(e) == n]
    if exact:
        return exact[0]
    # Разрешён только «хвост» модификации: «.10» или «М2» — иначе «ЯМЗ-53» совпало бы с «ЯМЗ-536»
    prefix = [e for e in ENGINES if _norm(e).startswith(n) and _SUFFIX.fullmatch(_norm(e)[len(n) :])]
    return prefix[0] if len(prefix) == 1 else None


def documents_for_engine(engine: str) -> tuple[Document, ...]:
    """Документы двигателя. Неизвестный двигатель — пусто, а не «все документы»."""
    canon = canonical_engine(engine)
    if canon is None:
        return ()
    return tuple(d for d in DOCUMENTS if canon in d.engines)
