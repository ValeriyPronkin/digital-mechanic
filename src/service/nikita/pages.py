"""Переходник: страницы руководств для кода Никиты — из нашего индекса (`.index/fragments.jsonl`).

У Никиты это `app/pages.py` над его базой знаний (две текстовые формы страницы, раздел, вид, расшифровка скана).
Здесь: текст страницы — фрагменты страницы по порядку (обе формы — один текст), раздел — поле `section`
фрагментов, вид — по заголовку страницы («Моменты затяжки» → приложение моментов, «Содержание» → оглавление),
расшифровка — фрагменты OCR. Страницы другой модификации — `registry/page_scope.yaml` Никиты; функции
`_scope_entries`, `_page_scope`, `_page_parts`, `partly_other_variant`, `other_variant` перенесены дословно.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml

from service.nikita.manuals import ROOT

PAGE_SCOPE_PATH = ROOT / "registry" / "page_scope.yaml"

KIND_TORQUE_APPENDIX = "torque_appendix"
KIND_CONTENTS = "contents"
_TORQUE_TITLE = re.compile(r"момент\w*\s+затяжки", re.I)
_CONTENTS_TITLE = re.compile(r"^\s*(?:содержание|оглавление)\b", re.I | re.M)


_INDEX: Any = None


def bind(index: Any) -> None:
    """Индекс, из которого берутся страницы (тот же, что у поиска): задаёт NikitaSearcher."""
    global _INDEX
    _INDEX = index
    _store.cache_clear()


@lru_cache(maxsize=1)
def _store() -> dict[tuple[str, int], dict[str, Any]]:
    """(doc_id, страница) → текст, текст OCR, раздел — из привязанного индекса."""
    pages: dict[tuple[str, int], dict[str, Any]] = {}
    for f in getattr(_INDEX, "fragments", []):
        p = pages.setdefault((f.doc_id, int(f.page)), {"lines": [], "ocr": [], "section": ""})
        target = p["ocr"] if f.source == "OCR" else p["lines"]
        for ln in f.text.splitlines():
            if ln.strip() and ln not in target[-3:]:  # повторы строк на стыках фрагментов
                target.append(ln)
        if not p["section"] and f.section:
            p["section"] = f.section
    return pages


def _get(manual_id: str, page: int) -> dict[str, Any]:
    return _store().get((manual_id, int(page)), {"lines": [], "ocr": [], "section": ""})


def get_page(engine_model: str, manual_id: str, page: int) -> str:
    return "\n".join(_get(manual_id, page)["lines"])


def get_flat(engine_model: str, manual_id: str, page: int) -> str:
    return get_page(engine_model, manual_id, page)  # у нас одна текстовая форма страницы


def get_transcript(engine_model: str, manual_id: str, page: int) -> str:
    return "\n".join(_get(manual_id, page)["ocr"])


def get_section(engine_model: str, manual_id: str, page: int) -> str:
    return str(_get(manual_id, page)["section"])


def get_kind(engine_model: str, manual_id: str, page: int) -> str:
    head = "\n".join(_get(manual_id, page)["lines"][:6])
    if _TORQUE_TITLE.search(head):
        return KIND_TORQUE_APPENDIX
    if _CONTENTS_TITLE.search(head):
        return KIND_CONTENTS
    return ""


# ---- дословно из app/pages.py Никиты ----
@lru_cache(maxsize=1)
def _page_scope() -> dict[tuple[str, str, int], str]:
    """`registry/page_scope.yaml` as (engine, manual, page) → reason. Empty if the file is absent."""
    if not PAGE_SCOPE_PATH.exists():
        return {}
    return _scope_entries(part=False)


def _scope_entries(part: bool) -> dict[tuple[str, str, int], str]:
    entries = yaml.safe_load(PAGE_SCOPE_PATH.read_text(encoding="utf-8")) or []
    return {
        (str(entry["engine"]), str(entry["manual"]), int(page)): str(entry["reason"])
        for entry in entries
        if bool(entry.get("part")) == part
        for page in entry["pages"]
    }


@lru_cache(maxsize=1)
def _page_parts() -> dict[tuple[str, str, int], str]:
    """The entries of `registry/page_scope.yaml` marked `part: true`: a page that stays in the index
    because most of it is about this engine, while some lines on it belong to another variant."""
    if not PAGE_SCOPE_PATH.exists():
        return {}
    return _scope_entries(part=True)


def partly_other_variant(engine_model: str, manual_id: str, page: int) -> str | None:
    """Which lines of the page are about another variant and where this engine's own text is, else None.
    Shown to the model with the page."""
    return _page_parts().get((engine_model, manual_id, page))


def other_variant(engine_model: str, manual_id: str, page: int) -> str | None:
    """Why the page is not about this engine (it is titled for another variant only), else None.

    Such a page is left out of the engine's search index; it can still be read by number.
    """
    return _page_scope().get((engine_model, manual_id, page))
