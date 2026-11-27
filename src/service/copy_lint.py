"""The machine-checkable rules of docs/copy-rules.md, applied to a piece of Russian text.

Ported from Nikita's version (`app/voice.py`, written in this sprint); only the path of the rules changed.
The rules are not written here. `[banned]`, `[allow]` and `[units]` come from the ```slop-lint``` block
of docs/copy-rules.md; this module only knows how to read that block and the typography mechanics (what
counts as a decimal point, where a non-breaking space goes). tests/test_copy_lint.py runs `violations`
over the strings the mechanic sees.

The doc is read on first use, not on import: the product itself never calls this module.

Rules reported in `Violation.rule`:

- `banned`: a `[banned]` pattern. Matched on whole words (a pattern never starts or ends inside a word),
  case-insensitive, with «ё» folded to «е» in both the pattern and the text.
- `exclamation`, `emoji`: calm voice.
- `quotes`: a straight or curly double quote where «ёлочки» belong.
- `ellipsis`: three dots instead of «…».
- `decimal-comma`: a number with a decimal point. Not a decimal: a designation with several dots or with
  letters or a hyphen attached («236.01.01 РК», «ЗМЗ‑5234.10», «40904.1000400-21») and a version right
  after a name in Latin letters («Python 3.12»).
- `nbsp-unit`: a regular space, or none, between a number and a unit of `[units]`. «с» followed by a
  lowercase word is read as the preposition («проверка 12 с помехами»), not as seconds.
- `nbsp-after`: a regular space, or none, after «стр.» or «№» before the number.
- `latin`: a word in Latin letters that is neither a name of `[allow]` (matched exactly) nor an
  identifier. An identifier is one to four capital Latin letters, an optional hyphen, then digits:
  «S-0005», «TKT‑0003», «F02», a source handle «S12». Nothing else passes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

VOICE_DOC = Path(__file__).resolve().parents[2] / "docs" / "copy-rules.md"


Span = tuple[int, int]


@dataclass(frozen=True)
class Violation:
    rule: str  # see the module docstring
    fragment: str  # the offending piece of the text
    suggestion: str  # what to write instead
    start: int
    end: int
    pattern: str = ""  # for `banned`: the pattern as docs/copy-rules.md writes it


@dataclass(frozen=True)
class BannedRule:
    source: str
    suggestion: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class Rules:
    banned: tuple[BannedRule, ...]
    allow: tuple[str, ...]
    units: tuple[str, ...]


_BLOCK = re.compile(r"^```slop-lint\n(.*?)^```", re.DOTALL | re.MULTILINE)
_SECTION = re.compile(r"\[(banned|allow|units)\]")
_FOLD = str.maketrans({"ё": "е", "Ё": "Е"})


def _whole_words(source: str) -> re.Pattern[str]:
    """The pattern anchored so it never starts or ends inside a word. Python's `\\w` covers Cyrillic for
    str patterns, so «достаточно» does not hit «точно» and «Высокий» does not hit «Вы»."""
    return re.compile(rf"(?<!\w)(?:{source.translate(_FOLD)})(?!\w)", re.IGNORECASE)


def parse_rules(markdown: str) -> Rules:
    """Rules from the text of docs/copy-rules.md. Raises if the block is missing or a section is empty."""
    block = _BLOCK.search(markdown)
    if block is None:
        raise ValueError("no ```slop-lint``` block in the voice doc")
    banned: list[BannedRule] = []
    allow: list[str] = []
    units: list[str] = []
    section = None
    for raw in block.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if header := _SECTION.fullmatch(line):
            section = header.group(1)
        elif section == "banned":
            source, arrow, suggestion = (part.strip() for part in line.partition("→"))
            if not arrow or not source or not suggestion:
                raise ValueError(f"[banned] line without «pattern → suggestion»: {line}")
            banned.append(BannedRule(source, suggestion, _whole_words(source)))
        elif section == "allow":
            allow.append(line)
        elif section == "units":
            units.extend(line.split())
        else:
            raise ValueError(f"slop-lint line outside a section: {line}")
    if not (banned and allow and units):
        raise ValueError("the slop-lint block needs [banned], [allow] and [units]")
    return Rules(tuple(banned), tuple(allow), tuple(units))


@lru_cache
def load_rules(path: Path = VOICE_DOC) -> Rules:
    return parse_rules(path.read_text(encoding="utf-8"))


_EXCLAMATION = re.compile("!")
_EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b50\u2b55\ufe0f]")
_DOUBLE_QUOTE = re.compile('["“”„‟]')
_THREE_DOTS = re.compile(r"\.{3,}")
_DECIMAL_POINT = re.compile(r"(?<![\w‑\-])(?<!\d\.)(?<![A-Za-z] )\d+\.\d+(?![\w‑\-]|\.\d)")
_AFTER_ABBREVIATION = re.compile(r"(?<!\w)(?:стр\.|№)[ \t]*\w+", re.IGNORECASE)
_WORD = re.compile(r"\w+(?:[-‑]\w+)*")
_LATIN = re.compile(r"[A-Za-z]")
_IDENTIFIER = re.compile(r"[A-Z]{1,4}[-‑]?\d+")
_PREPOSITION_LOOKALIKES = {"с"}
_LOWERCASE_WORD_NEXT = re.compile(r"\s[а-яё]")

_PLAIN = (
    ("exclamation", _EXCLAMATION, "no exclamation marks: a plain sentence"),
    ("emoji", _EMOJI, "no emoji: a plain sentence"),
    ("quotes", _DOUBLE_QUOTE, "«ёлочки»"),
    ("ellipsis", _THREE_DOTS, "the one-character ellipsis «…»"),
)


@lru_cache
def _unit_patterns(units: tuple[str, ...]) -> tuple[re.Pattern[str], re.Pattern[str]]:
    names = "|".join(re.escape(unit) for unit in sorted(units, key=len, reverse=True))
    spaced = re.compile(rf"\d+(?:[.,]\d+)?[ \t]+({names})(?![\w·/²°])")
    glued = re.compile(rf"(?<![\w.,‑\-])\d+(?:,\d+)?({names})(?![\w·/²°])")
    return spaced, glued


@lru_cache
def _allowed_names(allow: tuple[str, ...]) -> re.Pattern[str]:
    names = "|".join(re.escape(name) for name in sorted(allow, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9_])(?:{names})(?![A-Za-z0-9_])")


def _exempt_spans(text: str, exempt: Iterable[str | Span]) -> list[Span]:
    spans: list[Span] = []
    for item in exempt:
        if isinstance(item, str):
            if item:
                spans.extend((m.start(), m.end()) for m in re.finditer(re.escape(item), text))
        else:
            spans.append((item[0], item[1]))
    return spans


def violations(text: str, exempt: Iterable[str | Span] = (), *, rules: Rules | None = None) -> list[Violation]:
    """Every break of the voice rules in `text`, in the order of the text.

    `exempt` lists what is not ours to edit: verbatim quotes from a manual, each either as the quote
    string (every occurrence in the text is skipped) or as a `(start, end)` span of the text. A violation
    that lies wholly inside an exempt piece is not reported, so «98…107,8» or «категорически запрещается»
    stay in the manual's notation. `rules` defaults to the block of docs/copy-rules.md.
    """
    rules = rules or load_rules()
    found: list[Violation] = []

    def add(rule: str, start: int, end: int, suggestion: str, pattern: str = "") -> None:
        found.append(Violation(rule, text[start:end], suggestion, start, end, pattern))

    folded = text.translate(_FOLD)
    for banned in rules.banned:
        for m in banned.regex.finditer(folded):
            add("banned", m.start(), m.end(), banned.suggestion, banned.source)

    for rule, regex, suggestion in _PLAIN:
        for m in regex.finditer(text):
            add(rule, m.start(), m.end(), suggestion)

    for m in _DECIMAL_POINT.finditer(text):
        add("decimal-comma", m.start(), m.end(), m.group().replace(".", ","))

    spaced, glued = _unit_patterns(rules.units)
    for regex in (spaced, glued):
        for m in regex.finditer(text):
            unit = m.group(1)
            if unit in _PREPOSITION_LOOKALIKES and _LOWERCASE_WORD_NEXT.match(text, m.end()):
                continue
            add("nbsp-unit", m.start(), m.end(), f"a non-breaking space (U+00A0) before «{unit}»")

    for m in _AFTER_ABBREVIATION.finditer(text):
        add("nbsp-after", m.start(), m.end(), "a non-breaking space (U+00A0) after «стр.» and «№»")

    # Allowed names are blanked first, so «Docker-образ» leaves only its Russian half to look at.
    without_names = _allowed_names(rules.allow).sub(lambda m: " " * len(m.group()), text)
    for m in _WORD.finditer(without_names):
        if _LATIN.search(m.group()) and not _IDENTIFIER.fullmatch(m.group()):
            add("latin", m.start(), m.end(), "a Russian word, or the name added to [allow] in docs/copy-rules.md")

    spans = _exempt_spans(text, exempt)
    kept = [v for v in found if not any(start <= v.start and v.end <= end for start, end in spans)]
    return sorted(kept, key=lambda v: (v.start, v.end, v.rule))
