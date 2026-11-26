# Перенесено из pronkinnikita/digital-mechanic (автор — Никита, pronkinnikita), коммит 2855f726a4,
# с разрешения команды 27.11.2026. Изменены только импорты (app.* → service.nikita.*); логика — без изменений.
"""BM25 over the page text of one engine's manuals, in process (spec §4.1, §4.2).

One index per engine set (the pages of `manuals_for(engine_model)`), built on first use and cached. A page
of another engine is never in the index of this one, so a search cannot return it (spec §3, invariant 1).
A page titled for another engine variant only (`registry/page_scope.yaml`) is left out as well.

A page is indexed by its flat text, where words are whole («подшипников», not «по дшипнико в»). pdfium
runs table cells together on some pages where the layout text keeps them apart, so a word counts as many
times as the form that has it more often. The words of the page's section count too, at half weight.

Ranking is BM25 over whole pages, then the best candidates are re-ranked by how much of the query their
best passage (1–3 adjacent lines) covers: a norm sits in one table row, not spread over a page. The same
passage is the snippet. For a page transcribed from its image the passage may come from the transcript.
"""

import math
import re
import textwrap
import threading
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

import yaml

from service.nikita import pages
from service.nikita.lines import line_key, repeated
from service.nikita.manuals import ROOT, manuals_for
from service.nikita.tokens import join_broken_words, tokenize

GLOSSARY_PATH = ROOT / "registry" / "glossary.yaml"

K1 = 1.2
B = 0.75
# A glossary expansion counts for less than a word the mechanic typed.
EXPANSION_WEIGHT = 0.5
# A word of the page's section line counts for this much of a word of the page itself.
SECTION_WEIGHT = 0.5
# A line repeated on this share of a manual's pages is a table head or a stock phrase: not indexed.
# (Running headers and footers are already removed from the seed by `pipeline/clean.py`.)
BOILERPLATE_SHARE = 0.2
BOILERPLATE_MIN_PAGES = 20
# A page of a kind is lifted by this share when the query names what the kind is about, so that it
# outranks an ordinary page with the same score.
KIND_BOOST = 0.1
KIND_TERMS: dict[str, frozenset[str]] = {
    pages.KIND_TORQUE_APPENDIX: frozenset(tokenize("момент затяжки")),
}
# BM25 candidates that are re-ranked, and how much full coverage of the query by one passage adds.
POOL = 30
PASSAGE_WEIGHT = 1.0
PASSAGE_LINES = 3
SNIPPET_CHARS = 240

_BROKEN_WORD = re.compile(r"[а-яё]-$", re.IGNORECASE)
_WORD_TAIL = re.compile(r"\s*([а-яё]+)", re.IGNORECASE)


@dataclass(frozen=True)
class Hit:
    manual_id: str
    page: int
    score: float
    snippet: str


@dataclass(frozen=True)
class _Index:
    docs: tuple[tuple[str, int], ...]
    postings: dict[str, tuple[tuple[int, float], ...]]
    idf: dict[str, float]
    length_norm: tuple[float, ...]
    boilerplate: dict[str, frozenset[str]]


def _content_lines(text: str, boilerplate: frozenset[str]) -> list[str]:
    return [line for line in text.split("\n") if line.strip() and line_key(line) not in boilerplate]


def _page_terms(texts: tuple[str, ...], section: str, boilerplate: frozenset[str]) -> dict[str, float]:
    """Term weights of one page: the largest count among its text forms (layout, flat and, where the page
    was transcribed from its image, the transcript), plus the section at its weight."""
    counts = [Counter(tokenize("\n".join(_content_lines(text, boilerplate)))) for text in texts if text]
    merged: Counter[str] = Counter()
    for count in counts:
        merged |= count
    terms: dict[str, float] = dict(merged)
    for term, count in Counter(tokenize(section)).items():
        terms[term] = terms.get(term, 0) + SECTION_WEIGHT * count
    return terms


def _build(engine_model: str) -> _Index:
    docs: list[tuple[str, int]] = []
    doc_terms: list[dict[str, float]] = []
    boilerplate: dict[str, frozenset[str]] = {}
    for manual in manuals_for(engine_model):
        numbers = range(1, manual.pages + 1)
        forms = [
            (pages.get_flat(engine_model, manual.id, n), pages.get_page(engine_model, manual.id, n)) for n in numbers
        ]
        floor = max(BOILERPLATE_MIN_PAGES, BOILERPLATE_SHARE * len(forms))
        boilerplate[manual.id] = repeated(((*flat.split("\n"), *text.split("\n")) for flat, text in forms), floor)
        for n, texts in zip(numbers, forms, strict=True):
            if pages.other_variant(engine_model, manual.id, n) is not None:
                continue
            docs.append((manual.id, n))
            section = pages.get_section(engine_model, manual.id, n)
            forms_of_page = (*texts, pages.get_transcript(engine_model, manual.id, n))
            doc_terms.append(_page_terms(forms_of_page, section, boilerplate[manual.id]))

    lengths = [sum(terms.values()) for terms in doc_terms]
    average = (sum(lengths) / len(lengths)) if lengths else 0.0
    postings: dict[str, list[tuple[int, float]]] = {}
    for doc, terms in enumerate(doc_terms):
        for term, tf in terms.items():
            postings.setdefault(term, []).append((doc, tf))
    count = len(docs)
    return _Index(
        docs=tuple(docs),
        postings={term: tuple(rows) for term, rows in postings.items()},
        idf={term: math.log(1 + (count - len(rows) + 0.5) / (len(rows) + 0.5)) for term, rows in postings.items()},
        length_norm=tuple(K1 * (1 - B + B * length / average) if average else K1 for length in lengths),
        boilerplate=boilerplate,
    )


_indexes: dict[tuple[tuple[str, ...], frozenset[tuple[str, int]]], _Index] = {}
_build_lock = threading.Lock()


def index_for(engine_model: str) -> _Index:
    """The index of this engine's manuals. Engines share an index when they share the manual set and
    the pages left out of it: two variants of one manual each lose the pages titled for the other."""
    manuals = tuple(m.id for m in manuals_for(engine_model))
    left_out = frozenset(
        (m.id, n)
        for m in manuals_for(engine_model)
        for n in range(1, m.pages + 1)
        if pages.other_variant(engine_model, m.id, n) is not None
    )
    key = (manuals, left_out)
    with _build_lock:
        if key not in _indexes:
            _indexes[key] = _build(engine_model)
        return _indexes[key]


def content_lines(engine_model: str, manual_id: str, page: int, flat: bool = False) -> list[str]:
    """The lines of a page without blank lines and without the lines repeated all over the manual.

    The layout text the model reads by default; the flat text with `flat`.
    """
    text = (pages.get_flat if flat else pages.get_page)(engine_model, manual_id, page)
    return _content_lines(text, index_for(engine_model).boilerplate[manual_id])


@lru_cache(maxsize=1)
def glossary() -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """`registry/glossary.yaml` as (tokens of a shop word, tokens of the manuals' terms). Empty if absent."""
    if not GLOSSARY_PATH.exists():
        return ()
    raw = yaml.safe_load(GLOSSARY_PATH.read_text(encoding="utf-8")) or {}
    entries = []
    for term, expansions in raw.items():
        key = tuple(tokenize(str(term)))
        added = tuple(dict.fromkeys(t for e in expansions or () for t in tokenize(str(e))))
        if key and added:
            entries.append((key, added))
    return tuple(entries)


def _contains(tokens: list[str], key: tuple[str, ...]) -> bool:
    return any(tuple(tokens[i : i + len(key)]) == key for i in range(len(tokens) - len(key) + 1))


def query_terms(query: str) -> dict[str, float]:
    """Query tokens with weights: the mechanic's words at 1, glossary expansions below that."""
    tokens = tokenize(query)
    weights = dict.fromkeys(tokens, 1.0)
    for key, added in glossary():
        if _contains(tokens, key):
            for token in added:
                weights.setdefault(token, EXPANSION_WEIGHT)
    return weights


# Ten since scanned pages compete for the passage lift: with eight, the acceptance-test tables of a repair
# manual pushed the technical data page of the operation manual out of the list (golden question idle-236).
RESULTS = 10
FORMS = ("flat", "layout", "scan")
SCAN_LINE_CHARS = 90


@lru_cache(maxsize=4096)
def _page_lines(engine_model: str, manual_id: str, page: int, form: str) -> tuple[tuple[str, frozenset[str]], ...]:
    """Content lines of one text form of a page with their tokens: the flat text, the layout text or the
    transcript of the page image (empty for most pages). A word broken at a line end belongs to its first
    line."""
    if form == "scan":
        # A transcript writes a table row as one line of any length. Cut to the width of a printed line,
        # or a passage of three such rows would cover far more of a query than three lines of a text page.
        transcript = pages.get_transcript(engine_model, manual_id, page)
        rows = _content_lines(transcript, index_for(engine_model).boilerplate[manual_id])
        lines = [piece for row in rows for piece in textwrap.wrap(row, SCAN_LINE_CHARS) or [row]]
    else:
        lines = content_lines(engine_model, manual_id, page, form == "flat")
    texts = list(lines)
    for i in range(len(texts) - 1):
        head, tail = texts[i].rstrip(), _WORD_TAIL.match(texts[i + 1])
        if tail and _BROKEN_WORD.search(head):
            texts[i], texts[i + 1] = head[:-1] + tail[1], texts[i + 1][tail.end() :]
    return tuple((line, frozenset(tokenize(text))) for line, text in zip(lines, texts, strict=True))


@lru_cache(maxsize=4096)
def _section_terms(engine_model: str, manual_id: str, page: int) -> frozenset[str]:
    return frozenset(tokenize(pages.get_section(engine_model, manual_id, page)))


def _best_passage(
    lines: tuple[tuple[str, frozenset[str]], ...], gains: dict[str, float], context: frozenset[str]
) -> tuple[str, float]:
    """The 1–3 adjacent lines that carry the most of the query, and the share of the query they carry.

    The lines are read under the page's section: a query word the section has and the lines lack counts
    at the section's weight («Мкр=135±15» under «Установка … крышек коренных подшипников»).
    """
    found = [gains.keys() & terms for _, terms in lines]
    best, best_gain = (0, min(1, len(lines))), 0.0
    for size in range(1, PASSAGE_LINES + 1):
        for start in range(len(lines) - size + 1):
            inside = set().union(*found[start : start + size])
            gain = sum(gains[term] for term in inside)
            gain += SECTION_WEIGHT * sum(gains[term] for term in context - inside if term in gains)
            if gain > best_gain + 1e-9:
                best, best_gain = (start, size), gain
    text = " ".join(" ".join(line for line, _ in lines[best[0] : best[0] + best[1]]).split())
    text = join_broken_words(text)
    if len(text) > SNIPPET_CHARS:
        text = text[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"
    total = sum(gains.values())
    return text, (best_gain / total if total else 0.0)


def search(engine_model: str, query: str, k: int = RESULTS) -> list[Hit]:
    """The `k` best pages of this engine's manuals for the query, best first. Empty if nothing matches."""
    index = index_for(engine_model)
    asked = query_terms(query)
    gains = {term: w * index.idf[term] for term, w in asked.items() if term in index.idf}
    boosted = {kind for kind, terms in KIND_TERMS.items() if terms <= asked.keys()}
    scores: dict[int, float] = {}
    for term, gain in gains.items():
        for doc, tf in index.postings[term]:
            scores[doc] = scores.get(doc, 0.0) + gain * tf * (K1 + 1) / (tf + index.length_norm[doc])
    pool = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[: max(k, POOL)]
    hits = []
    for doc, score in pool:
        manual_id, page = index.docs[doc]
        # The passage is looked for in every text form; the flat one wins a tie, it reads better. A page
        # that exists only as a scan has its passage in the transcript: without it the page would get no
        # lift here and sink below every page with a text layer.
        context = _section_terms(engine_model, manual_id, page)
        snippet, coverage = max(
            (_best_passage(_page_lines(engine_model, manual_id, page, form), gains, context) for form in FORMS),
            key=lambda found: found[1],
        )
        score *= 1 + PASSAGE_WEIGHT * coverage
        if pages.get_kind(engine_model, manual_id, page) in boosted:
            score *= 1 + KIND_BOOST
        hits.append(Hit(manual_id, page, round(score, 3), snippet))
    return sorted(hits, key=lambda hit: -hit.score)[:k]
