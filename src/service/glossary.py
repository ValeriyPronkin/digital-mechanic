"""Глоссарий цеховых слов → термины руководств и определение языка вопроса кодом (штурман 26.11).

Детерминированный поиск: вместо плана от модели (формулировки менялись от прогона к прогону) русский вопрос ищется
сам по себе + термины глоссария с весом 0,5. Модель для плана — только если вопрос не на русском (перевод).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "data" / "glossary.json"
_LATIN = re.compile(r"[A-Za-z]")
_CYR = re.compile(r"[А-Яа-яЁё]")
_NOT_RU = re.compile(r"[ЎўҚқҒғҲҳӢӣӮӯҶҷЇїІіЄєҢңӘәӨөҮүҰұҺһ]")  # узбекская, таджикская кириллица и т.п.


@lru_cache(maxsize=1)
def _items() -> tuple[tuple[re.Pattern[str], str], ...]:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    return tuple((re.compile(i["words"], re.I), i["terms"]) for i in data["items"])


def expand(text: str) -> list[str]:
    """Термины руководства к цеховым словам вопроса (без повторов, в порядке глоссария)."""
    return list(dict.fromkeys(terms for pat, terms in _items() if pat.search(text)))


def needs_translation(text: str) -> bool:
    """Вопрос не на русском: буквы национальной кириллицы или латиницы больше, чем кириллицы."""
    if _NOT_RU.search(text):
        return True
    lat, cyr = len(_LATIN.findall(text)), len(_CYR.findall(text))
    return lat > cyr
