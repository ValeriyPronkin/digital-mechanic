# Перенесено из pronkinnikita/digital-mechanic (автор — Никита, pronkinnikita), коммит 2855f726a4,
# с разрешения команды 27.11.2026. Изменены только импорты (app.* → service.nikita.*); логика — без изменений.
"""Lines that repeat across the pages of a manual: running headers and footers, repeated table heads.

One implementation for both users: ingestion finds the running headers and footers with it and removes
them from the stored text (`pipeline/clean.py`); search finds the lines repeated all over a manual with it
and keeps them out of the index (`app/search.py`).
"""

import re
from collections import Counter
from collections.abc import Iterable

_NUMBER = re.compile(r"\d+(?:[-.,/]\d+)*")
_HAS_LETTER = re.compile(r"[a-zа-яё]")


def line_key(line: str) -> str:
    """A line with spacing, case, numbers and codes folded: «Страница 3» and «Страница 14» are one line.

    A line without letters keeps its digits: a date is the same line on every page, two callouts are not.
    """
    text = " ".join(line.split()).lower()
    return _NUMBER.sub("0", text) if _HAS_LETTER.search(text) else text


def repeated(pages: Iterable[Iterable[str]], floor: float, letterless: bool = False) -> frozenset[str]:
    """Keys of the lines found on at least `floor` of the pages; each page is given as its lines.

    Lines without letters count only when `letterless` is set.
    """
    seen: Counter[str] = Counter()
    for lines in pages:
        keys = {line_key(line) for line in lines}
        seen.update(key for key in keys if key and (letterless or _HAS_LETTER.search(key)))
    return frozenset(key for key, n in seen.items() if n >= floor)
