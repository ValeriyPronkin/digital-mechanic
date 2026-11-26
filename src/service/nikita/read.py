# Перенесено из pronkinnikita/digital-mechanic (автор — Никита, pronkinnikita), коммит 2855f726a4,
# с разрешения команды 27.11.2026: read_pages и соседние страницы из app/tools/manual.py.
# Изменено: импорты (app.* → service.nikita.*); метка страницы — через handle_for (у нас R…, у Никиты S…);
# проверка «руководство этого двигателя» — по manuals_for (у Никиты page_store.manual_in_scope). Логика — его.
"""Чтение страниц руководства целиком (spec §4.2 Никиты).

Страница приходит с меткой, разделом и пометкой «для другой модификации» (registry/page_scope.yaml). Соседняя
страница добавляется сама, если запрошенная начинается с «Продолжение таблицы» или обрывается на середине.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from service.nikita import copy, search
from service.nikita import pages as page_store
from service.nikita.manuals import BY_ID, Manual, manuals_for

MAX_PAGES = 6
# How far an open end is followed: a page that stops mid-instruction brings the next one, and if that one
# stops mid-instruction too, one more. A fault table can run for ten pages; the rest is the model's to ask.
MAX_FOLLOWED = 2

_CONTINUED_TABLE = re.compile(r"продолжение\s+табл", re.IGNORECASE)
_HAS_LETTER = re.compile(r"[A-Za-zА-Яа-яЁё]")
_WORD_BREAK = re.compile(r"[а-яё]-$")
_NAME_FOLD = str.maketrans({"ё": "е", "–": "-", "—": "-", "−": "-", "«": " ", "»": " ", '"': " "})

Handle = Callable[[str, int], str]


def _name_key(name: str) -> str:
    return " ".join(name.lower().translate(_NAME_FOLD).split())


def _names(manual: Manual) -> set[str]:
    return {_name_key(n) for n in (manual.id, manual.designation, manual.short, manual.title)}


def _available(engine_model: str) -> str:
    listed = "; ".join(f"{m.short} (стр. 1–{m.pages})" for m in manuals_for(engine_model))
    return copy.MANUAL_AVAILABLE.format(engine=engine_model, manuals=listed)


def _find_manual(engine_model: str, name: str) -> Manual | None:
    """The manual of this engine the model means: by id, designation, short name or a distinct part of one."""
    key = _name_key(name)
    found = [m for m in BY_ID.values() if key in _names(m)]
    if not found and len(key) >= 2:
        found = [m for m in manuals_for(engine_model) if any(key in n or n in key for n in _names(m))]
    if len(found) != 1:
        return None
    own = {m.id: m for m in manuals_for(engine_model)}
    return own.get(found[0].id)  # руководство другого двигателя — None, как OutOfScope у Никиты


def _as_page_numbers(asked: Any) -> list[int]:
    """Whole numbers from whatever the model sent, in order, without repeats. Anything else is dropped."""
    out: list[int] = []
    for item in asked if isinstance(asked, list | tuple) else [asked]:
        if isinstance(item, str) and item.strip().lstrip("-").isdigit():
            item = int(item)
        if isinstance(item, int) and not isinstance(item, bool) and item not in out:
            out.append(item)
    return out


def _starts_with_continued_table(text: str) -> bool:
    top = [line for line in text.split("\n") if line.strip()][:6]
    return any(_CONTINUED_TABLE.match(line.strip()) for line in top)


def _open_end(engine_model: str, manual_id: str, page: int) -> str | None:
    """The reason template if the page stops with the sentence or list unfinished, else None."""
    lines = [ln.rstrip() for ln in search.content_lines(engine_model, manual_id, page) if _HAS_LETTER.search(ln)]
    if not lines:
        return None
    last = lines[-1]
    if last.endswith(":"):
        return copy.MANUAL_ADDED_NEXT_COLON
    if last.endswith((",", ";")) or _WORD_BREAK.search(last):
        return copy.MANUAL_ADDED_NEXT_BREAK
    return None


def _neighbours(engine_model: str, manual: Manual, wanted: list[int]) -> dict[int, str]:
    """Pages to read along with the requested ones, each with the reason, so no table or step is cut."""
    added: dict[int, str] = {}
    for page in wanted:
        before, after = page - 1, page + 1
        text = page_store.get_page(engine_model, manual.id, page)
        if before >= 1 and before not in wanted and before not in added and _starts_with_continued_table(text):
            added[before] = copy.MANUAL_ADDED_PREVIOUS.format(page=page, added=before)
        # An open end is followed: the page it brings may stop mid-instruction as well.
        last, followed = page, 0
        while followed < MAX_FOLLOWED and last + 1 <= manual.pages:
            after = last + 1
            if after in wanted:
                break
            reason = _open_end(engine_model, manual.id, last)
            if reason is None:
                break
            added.setdefault(after, reason.format(page=last, added=after))
            last, followed = after, followed + 1
    return added


_SECTION_HEAD = re.compile(r"\d+(?:\.\d+)*\.?\s+[А-ЯЁ][А-ЯЁ ,\-]{8,}")  # «12 ПОВЫШЕННАЯ ВИБРАЦИЯ ДВИГАТЕЛЯ»


def _table_goes_on(engine_model: str, manual: Manual, last: int) -> bool:
    """The page after `last` continues a table («Продолжение таблицы 3») with more rows of the same part
    of it, so what was returned stops in the middle. A next page that opens a new numbered part of the
    table, written in capitals, is another subject: the list the model was reading ended on `last`."""
    if last >= manual.pages:
        return False
    text = page_store.get_page(engine_model, manual.id, last + 1)
    if not _starts_with_continued_table(text):
        return False
    rows = [line.strip() for line in text.split("\n") if line.strip()]
    start = next((i for i, row in enumerate(rows) if _CONTINUED_TABLE.match(row)), 0)
    # the first row under «Продолжение таблицы» and the column heads, which are words without a number
    first = next((row for row in rows[start + 1 : start + 4] if row[:1].isdigit()), "")
    return not _SECTION_HEAD.match(first)


def _failure(error: str) -> dict[str, Any]:
    return {"error": error, "pages": [], "added": [], "skipped": [], "note": None}


def read_pages(engine_model: str, handle_for: Handle, manual: str, pages: Any) -> dict[str, Any]:
    """Full text of up to six pages of one manual of this engine, each prefixed with its source handle.

    Under the handle line comes the page's section (where it has one) and, for a page titled for another
    engine variant, a note saying so. `manual` is the id, the designation or the short name. A neighbour
    page is added when a requested page starts with a continued table or stops mid-instruction. Problems
    come back in `error`, never as an exception: the model reads the explanation and asks again.
    """
    if not manuals_for(engine_model):
        return _failure(copy.MANUAL_NO_MANUALS.format(engine=engine_model))
    found = _find_manual(engine_model, str(manual))
    if found is None:
        unknown = copy.MANUAL_UNKNOWN_MANUAL.format(manual=str(manual).strip(), engine=engine_model)
        return _failure(f"{unknown} {_available(engine_model)}")
    numbers = _as_page_numbers(pages)
    if not numbers:
        return _failure(copy.MANUAL_NO_PAGES_ASKED)

    in_range = [n for n in numbers if 1 <= n <= found.pages]
    missing = [n for n in numbers if n not in in_range]
    wanted, skipped = in_range[:MAX_PAGES], in_range[MAX_PAGES:]
    added = _neighbours(engine_model, found, wanted)
    skipped = [n for n in skipped if n not in added]

    result: dict[str, Any] = {"manual": found.short, "pages": [], "added": [], "skipped": skipped, "note": None}
    notes: list[str] = []
    for page in sorted([*wanted, *added]):
        handle = handle_for(found.id, page)
        text = page_store.get_page(engine_model, found.id, page)
        header = [f"[{handle}] {found.short}, стр. {page}"]
        if section := page_store.get_section(engine_model, found.id, page):
            header.append(copy.MANUAL_SECTION.format(section=section))
        if reason := page_store.other_variant(engine_model, found.id, page):
            header.append(copy.MANUAL_OTHER_VARIANT.format(engine=engine_model, reason=reason))
        if reason := page_store.partly_other_variant(engine_model, found.id, page):
            header.append(copy.MANUAL_PARTLY_OTHER_VARIANT.format(engine=engine_model, reason=reason))
        body = [*header, text]
        if transcript := page_store.get_transcript(engine_model, found.id, page):
            body += ["", copy.MANUAL_TRANSCRIPT, transcript]
        result["pages"].append({"source": handle, "manual_id": found.id, "pdf_page": page, "text": "\n".join(body)})
        if page in added:
            result["added"].append({"source": handle, "pdf_page": page, "reason": added[page]})
            notes.append(copy.MANUAL_ADDED.format(added=page, reason=added[page]))
    if skipped:
        notes.append(copy.MANUAL_SKIPPED.format(limit=MAX_PAGES, pages=", ".join(map(str, skipped))))
    returned = sorted([*wanted, *added])
    if returned and _table_goes_on(engine_model, found, returned[-1]):
        notes.append(copy.MANUAL_TABLE_CONTINUES.format(next=returned[-1] + 1))
    if missing:
        absent = copy.MANUAL_NO_SUCH_PAGES.format(
            manual=found.short, last=found.pages, pages=", ".join(map(str, missing))
        )
        result["error"] = f"{absent} {_available(engine_model)}"
    result["note"] = " ".join(notes) or None
    return result
