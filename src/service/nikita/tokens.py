# Перенесено из pronkinnikita/digital-mechanic (автор — Никита, pronkinnikita), коммит 2855f726a4,
# с разрешения команды 27.11.2026. Изменены только импорты (app.* → service.nikita.*); логика — без изменений.
"""Search tokens for Russian manual text: lemmas for words, raw tokens for numbers and part codes.

The page text and the query go through the same `tokenize`, so a match needs no further normalisation.
"""

import re
from functools import lru_cache

import pymorphy3

# A hyphen at a line end inside a Cyrillic word: «компрес-\n   сионное» is one word.
_HYPHEN_BREAK = re.compile(r"(?<=[а-я])[-­][ \t]*\n[ \t]*(?=[а-я])")
# The same break after the lines were joined: «под- шипников». «двух- или трёхдисковое» is left alone.
_JOINED_BREAK = re.compile(r"(?<=[а-яё]{2})- (?!или\b)(?=[а-яё]{2})")
_TOKEN = re.compile(r"[a-zа-я0-9]+(?:[.,/\-][a-zа-я0-9]+)*")
_CYRILLIC = re.compile(r"[а-я]+")
_DECIMAL = re.compile(r"\d+[.,]\d+")
_SEPARATORS = re.compile(r"[.,/\-]")
_CODE_SEPARATORS = re.compile(r"[/\-]")

# «ЯМЗ–236М2» is printed with an en dash; a dash between words has spaces around it and never joins tokens.
_FOLD = str.maketrans({"ё": "е", "–": "-", "−": "-", "‐": "-", "‑": "-"})
# In a token with digits, Cyrillic letters that look like Latin ones are folded: «М16» typed either way.
_LOOKALIKES = str.maketrans("авекмнорстух", "abekmhopctyx")

_STOP_WORDS = (
    "и в во не на с со к ко по из за от до для при или а но что как это этот то тот же ли бы о об у "
    "он она оно они его ее их быть который так также если чем под над между через после перед без "
    "весь все свой себя мы вы я ты да нет уже еще только где когда там тут здесь нужно надо можно "
    "какой такой чтобы либо ни мой ваш наш сам"
)
STOP_WORDS = frozenset(_STOP_WORDS.split())


@lru_cache(maxsize=1)
def _morph() -> pymorphy3.MorphAnalyzer:
    return pymorphy3.MorphAnalyzer(lang="ru")


@lru_cache(maxsize=200_000)
def lemma(word: str) -> str:
    """Dictionary form of a lowercase Cyrillic word, with «ё» folded to «е»."""
    return _morph().parse(word)[0].normal_form.replace("ё", "е")


def normalize(text: str) -> str:
    """Lowercase, «ё» → «е», one form of hyphen, hyphenated line breaks joined."""
    return _HYPHEN_BREAK.sub("", text.lower().translate(_FOLD))


def join_broken_words(text: str) -> str:
    """«под- шипников» → «подшипников»: a word hyphenated at a line end, met after the lines were joined."""
    return _JOINED_BREAK.sub("", text)


def _word(part: str) -> str | None:
    if len(part) < 2 or part in STOP_WORDS:
        return None
    lem = lemma(part)
    return None if lem in STOP_WORDS else lem


def _raw(part: str) -> str:
    part = part.translate(_LOOKALIKES)
    return part.replace(".", ",") if _DECIMAL.fullmatch(part) else part


def _code_forms(token: str) -> list[str]:
    """«236-1004045-б3» and its leading part «236-1004045»: a part is often named without its suffix."""
    cuts = [m.start() for m in _CODE_SEPARATORS.finditer(token)]
    return [token, *(token[:cut] for cut in reversed(cuts[1:]))] if cuts else []


def tokenize(text: str) -> list[str]:
    """Tokens of a page or a query.

    Cyrillic words become lemmas. A token with a digit or a Latin letter is kept raw; a code or a range
    («236-1004045-Б3», «0,08-0,18») yields the whole token, its leading parts and each part, so a query
    matches in whichever form the mechanic types it.
    """
    out: list[str] = []
    for token in _TOKEN.findall(normalize(text)):
        if any(c.isdigit() for c in token):
            parts = _CODE_SEPARATORS.split(token)
            out.extend(form.translate(_LOOKALIKES) for form in _code_forms(token))
        else:
            parts = _SEPARATORS.split(token)
        for part in parts:
            if _CYRILLIC.fullmatch(part):
                if (word := _word(part)) is not None:
                    out.append(word)
            elif part:
                out.append(_raw(part))
    return out
