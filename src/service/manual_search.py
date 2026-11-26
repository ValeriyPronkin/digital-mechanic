"""Тонкая прослойка над поиском по руководствам из issue #3 (`service.manuals.search.ManualIndex`).

Агент знает только `ManualSearcher.search(query, engine, k) -> list[ManualHit]`. Двигатель передаёт код из
карточки ТС, а не модель. Когда модуль #3 попадёт в main и индекс будет собран, `default_searcher()` подхватит
его сам; до тех пор — пустой поиск (STUB: search-until-#3): агент честно отвечает «в руководстве не нашёл».
"""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from service import glossary

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManualHit:
    manual_id: str  # стабильный id документа (doc_id из #3)
    manual: str  # обозначение документа для механика и для заявки (references[].manual)
    pdf_page: int  # номер страницы PDF с 1
    section: str
    text: str  # фрагмент, который видит модель; с ним сверяются цифры ответа


class ManualSearcher(Protocol):
    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]: ...


class EmptySearcher:
    """STUB: search-until-#3 — индекса ещё нет: ничего не находим, ничего не выдумываем."""

    available = False

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        return []


class IndexSearcher:
    """Адаптер над `ManualIndex` из #3."""

    available = True

    def __init__(self, index: Any) -> None:
        self.index = index
        self._pages: dict[tuple[str, int], str] | None = None

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        """Текст всей страницы PDF из индекса (фрагменты по порядку, повторы строк на стыках убраны) — для окна
        вокруг попадания: цифра часто стоит в соседнем фрагменте той же страницы (#28)."""
        if self._pages is None:
            pages: dict[tuple[str, int], list[str]] = {}
            for f in self.index.fragments:
                lines = pages.setdefault((f.doc_id, int(f.page)), [])
                for ln in f.text.splitlines():
                    if ln.strip() and ln not in lines[-3:]:
                        lines.append(ln)
            self._pages = {k: "\n".join(v) for k, v in pages.items()}
        return self._pages.get((manual_id, int(pdf_page)))

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        hits = self.index.search(query, engine, k=k, expand=glossary.expand(query))
        return [
            ManualHit(
                manual_id=h.fragment.doc_id,
                manual=h.fragment.designation,
                pdf_page=int(h.fragment.page),
                section=h.fragment.section,
                text=h.fragment.text,
            )
            for h in hits
        ]


def default_searcher() -> ManualSearcher:
    try:
        mod = importlib.import_module("service.manuals.search")
        return IndexSearcher(mod.ManualIndex.load())
    except (ImportError, FileNotFoundError, OSError) as exc:
        log.warning("поиск по руководствам недоступен (%s) — работает заглушка", exc)
        return EmptySearcher()


def manual_pdf(manual_id: str) -> Path | None:
    """Путь к PDF документа в MANUALS_DIR (для кликабельной ссылки), если каталог #3 доступен и файл на месте."""
    try:
        catalog = importlib.import_module("service.manuals.catalog")
    except ImportError:
        return None
    doc = next((d for d in catalog.DOCUMENTS if d.doc_id == manual_id), None)
    if doc is None:
        return None
    path = Path(os.environ.get("MANUALS_DIR", "./manuals")) / doc.file
    return path if path.is_file() else None
