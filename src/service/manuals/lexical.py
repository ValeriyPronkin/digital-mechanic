"""Поиск по словам: токены в начальной форме (pymorphy3) и BM25."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from functools import lru_cache

import pymorphy3

_WORD = re.compile(r"[а-яёa-z]+|\d+(?:[.,]\d+)?", re.I)
_STOP = frozenset(
    "и в во не на с со по к ко о об от до из за для при без над под же ли или а но что как это то так "
    "его ее её их он она оно они мы вы я у бы был была были быть есть".split()
)

_morph = pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=200_000)
def lemma(word: str) -> str:
    if not word or not word[0].isalpha():
        return word
    if not ("а" <= word[0] <= "я" or word[0] == "ё"):
        return word
    return str(_morph.parse(word)[0].normal_form)


def tokenize(text: str) -> list[str]:
    """Текст → леммы без стоп-слов. Числа остаются токенами («0,25» — один токен)."""
    out: list[str] = []
    for m in _WORD.finditer(text.lower().replace("ё", "е")):
        w = m.group(0).replace(",", ".")
        if w in _STOP:
            continue
        out.append(lemma(w).replace("ё", "е"))
    return out


class BM25:
    """Okapi BM25 по заранее токенизированным документам."""

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 0.0
        df: Counter[str] = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: Sequence[str], candidates: Iterable[int]) -> dict[int, float]:
        """Оценки только для кандидатов (после фильтра по двигателю); нулевые не возвращаются."""
        terms = [t for t in dict.fromkeys(query) if t in self.idf]
        out: dict[int, float] = {}
        if not terms:
            return out
        for i in candidates:
            tf = self.tf[i]
            norm = self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg or 1))
            s = 0.0
            for t in terms:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            if s > 0:
                out[i] = s
        return out
