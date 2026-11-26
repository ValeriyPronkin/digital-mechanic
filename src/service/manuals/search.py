"""Поиск по руководствам: фильтр по двигателю → BM25 + эмбеддинги (параллельно) → слияние RRF.

Фильтр по двигателю стоит ДО ранжирования: кандидаты — только фрагменты документов двигателя ТС,
поэтому чужое руководство в выдачу попасть не может. После ранжирования — повторная проверка.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .catalog import canonical_engine, documents_for_engine
from .index import Fragment, _normalize, index_dir, load_fragments
from .lexical import BM25, tokenize

RRF_K = 60
POOL = 50  # сколько лучших из каждого поиска идут в слияние


class UnknownEngineError(ValueError):
    """Двигателя нет в карте «двигатель → документы»: искать не в чем, всё подряд не ищем."""


@dataclass(frozen=True)
class Hit:
    fragment: Fragment
    score: float
    quote: str
    lexical_rank: int | None
    semantic_rank: int | None


def rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal Rank Fusion: сумма 1/(k + место) по спискам."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return fused


_SENT = re.compile(r"(?<=[.!?;:])\s+|\n+")


def make_quote(text: str, query_tokens: list[str], max_chars: int = 400) -> str:
    """Цитата: окно подряд идущих предложений фрагмента с наибольшим числом слов запроса."""
    parts = [p.strip() for p in _SENT.split(text) if p and p.strip()]
    if not parts:
        return ""
    q = set(query_tokens)
    hits = [len(q.intersection(tokenize(p))) for p in parts]
    best, best_score = (0, 0), -1.0
    for i in range(len(parts)):
        size, score, j = 0, 0, i
        while j < len(parts) and (size == 0 or size + len(parts[j]) + 1 <= max_chars):
            size += len(parts[j]) + 1
            score += hits[j]
            j += 1
        # при равенстве — окно, где совпадения начинаются раньше (цитата начинается по делу)
        adj = score - (0.01 * i if hits[i] == 0 else 0)
        if adj > best_score:
            best, best_score = (i, j), adj
    quote = " ".join(parts[best[0] : best[1]])
    return quote if len(quote) <= max_chars else quote[: max_chars - 1].rstrip() + "…"


class ManualIndex:
    def __init__(
        self,
        fragments: list[Fragment],
        vectors: np.ndarray[Any, np.dtype[np.float32]] | None = None,
        embed_query: Callable[[str], list[float]] | None = None,
    ) -> None:
        if vectors is not None and len(vectors) != len(fragments):
            raise ValueError("векторы не совпадают с фрагментами — пересоберите индекс")
        self.fragments = fragments
        self.vectors = vectors
        self.embed_query = embed_query
        self.bm25 = BM25([f.tokens or tokenize(f"{f.section}\n{f.text}") for f in fragments])
        self._by_doc: dict[str, list[int]] = {}
        for i, f in enumerate(fragments):
            self._by_doc.setdefault(f.doc_id, []).append(i)

    @classmethod
    def load(cls, path: Path | None = None, *, semantic: bool = True) -> ManualIndex:
        path = path or index_dir()
        frags_path = path / "fragments.jsonl"
        if not frags_path.exists():
            raise FileNotFoundError(f"индекс не собран: нет {frags_path} (make index)")
        frags = load_fragments(frags_path)
        vectors = None
        embed = None
        if semantic and (path / "vectors.npy").exists():
            from .yandex import EmbeddingClient, YandexConfig

            cfg = YandexConfig.from_env()
            if cfg:
                vectors = np.load(path / "vectors.npy")
                embed = EmbeddingClient(cfg, path / "cache" / "embeddings.jsonl").embed_query
        return cls(frags, vectors, embed)

    @property
    def semantic(self) -> bool:
        return self.vectors is not None and self.embed_query is not None

    def candidates(self, engine: str) -> list[int]:
        docs = documents_for_engine(engine)
        if not docs:
            raise UnknownEngineError(f"двигатель «{engine}» не найден в карте руководств")
        return [i for d in docs for i in self._by_doc.get(d.doc_id, [])]

    def search(self, query: str, engine: str, k: int = 5) -> list[Hit]:
        cand = self.candidates(engine)
        allowed_docs = {d.doc_id for d in documents_for_engine(engine)}
        q_tokens = tokenize(query)

        with ThreadPoolExecutor(2) as pool:
            sem_future = pool.submit(self.embed_query, query) if self.semantic and self.embed_query else None
            lex = self.bm25.scores(q_tokens, cand)
            lex_rank = sorted(lex, key=lambda i: -lex[i])[:POOL]
            sem_rank: list[int] = []
            if sem_future is not None and self.vectors is not None:
                try:
                    qv = _normalize(np.asarray([sem_future.result()], dtype=np.float32))[0]
                except Exception:  # noqa: BLE001  # сеть упала — работаем по словам, а не падаем
                    qv = None
                if qv is not None:
                    idx = np.asarray(cand, dtype=np.int64)
                    sims = self.vectors[idx] @ qv
                    top = np.argsort(-sims)[:POOL]
                    sem_rank = [int(idx[t]) for t in top]

        fused = rrf([r for r in (lex_rank, sem_rank) if r])
        order = sorted(fused, key=lambda i: -fused[i])
        hits: list[Hit] = []
        seen_pages: set[tuple[str, int]] = set()
        for i in order:
            f = self.fragments[i]
            if f.doc_id not in allowed_docs:  # второй рубеж: фильтр выше уже не пустил бы
                continue
            key = (f.doc_id, f.page)
            if key in seen_pages:  # одна страница — одна строка выдачи
                continue
            seen_pages.add(key)
            hits.append(
                Hit(
                    fragment=f,
                    score=fused[i],
                    quote=make_quote(f.text, q_tokens),
                    lexical_rank=lex_rank.index(i) + 1 if i in lex_rank else None,
                    semantic_rank=sem_rank.index(i) + 1 if i in sem_rank else None,
                )
            )
            if len(hits) >= k:
                break
        return hits


def normalize_engine_or_raise(engine: str) -> str:
    canon = canonical_engine(engine)
    if canon is None:
        raise UnknownEngineError(f"двигатель «{engine}» не найден в карте руководств")
    return canon
