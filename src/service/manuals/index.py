"""Сборка индекса руководств одной командой и его загрузка.

Каталог индекса (INDEX_DIR, по умолчанию `.index/`):
  passport.json     — паспорт каждого PDF: страниц, без текста, OCR, смещение номеров, оглавление;
  fragments.jsonl   — фрагменты с метками и токенами BM25;
  vectors.npy       — эмбеддинги фрагментов (строка i ↔ фрагмент i), если был ключ Yandex;
  cache/            — извлечённый текст по PDF, OCR, эмбеддинги: повторная сборка не платит и не ждёт.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .catalog import DOCUMENTS, Document
from .lexical import tokenize
from .text import TocEntry, chunk_text, detect_page_offset, page_title, parse_toc, section_for_page

log = logging.getLogger(__name__)

EXTRACT_VERSION = "4"  # поднять при изменении извлечения — кэш PDF пересоберётся
SOURCE_TEXT = "текст"
SOURCE_TABLE = "таблица"
SOURCE_OCR = "OCR"
LOW_TEXT_CHARS = 50


def manuals_dir() -> Path:
    return Path(os.environ.get("MANUALS_DIR", "./manuals")).expanduser()


def index_dir() -> Path:
    return Path(os.environ.get("INDEX_DIR", ".index")).expanduser()


@dataclass
class Fragment:
    id: str
    doc_id: str
    designation: str
    engines: list[str]
    kind: str  # эксплуатация / ремонт
    page: int  # номер страницы PDF с 1
    section: str  # раздел из оглавления
    source: str  # текст / таблица / OCR
    text: str
    tokens: list[str] = field(default_factory=list)


# ---------- извлечение одного PDF (в отдельном процессе, с кэшем) ----------


def _file_key(path: Path) -> str:
    st = path.stat()
    return hashlib.sha256(f"{path.name}|{st.st_size}|{int(st.st_mtime)}|{EXTRACT_VERSION}".encode()).hexdigest()[:16]


def extract_document(doc: Document, pdf_path: Path, cache_dir: Path) -> dict[str, Any]:
    """Текст страниц, таблицы, смещение номеров и оглавление одного PDF. Результат кэшируется."""
    from .pdf import read_pages, read_tables

    cache = cache_dir / f"{doc.doc_id}-{_file_key(pdf_path)}.json"
    if cache.exists():
        cached: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
        return cached
    pages = read_pages(pdf_path)
    offset = detect_page_offset([p.printed for p in pages])
    toc_lines = [ln for n in doc.toc_pages if 1 <= n <= len(pages) for ln in pages[n - 1].text.splitlines()]
    toc = parse_toc(toc_lines, offset or 0, len(pages))
    tables = read_tables(pdf_path)
    data = {
        "doc_id": doc.doc_id,
        "pages": [{"page": p.page, "raw": p.raw, "text": p.text, "printed": p.printed} for p in pages],
        "offset": offset,
        "toc": [asdict(e) for e in toc],
        "tables": [
            {"page": t.page, "tables": t.tables, "fault_rows": [asdict(r) for r in t.fault_rows]} for t in tables
        ],
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _extract_job(args: tuple[str, str, str]) -> dict[str, Any]:
    doc_id, pdf_path, cache_dir = args
    doc = next(d for d in DOCUMENTS if d.doc_id == doc_id)
    return extract_document(doc, Path(pdf_path), Path(cache_dir))


# ---------- фрагменты ----------


def _table_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(c for c in row if c) for row in rows)


def fragments_for_document(
    doc: Document, data: dict[str, Any], ocr_text: dict[int, str]
) -> tuple[list[Fragment], dict[str, Any]]:
    """Фрагменты одного документа и его паспорт."""
    toc = [TocEntry(**e) for e in data["toc"]]
    frags: list[Fragment] = []

    def section(page: int, text: str) -> str:
        if doc.section_from_page_title:
            return page_title(text)
        return section_for_page(toc, page)

    def add(page: int, source: str, text: str, sec: str) -> None:
        n = sum(1 for f in frags if f.page == page)
        frags.append(
            Fragment(
                id=f"{doc.doc_id}:{page}:{n}",
                doc_id=doc.doc_id,
                designation=doc.designation,
                engines=list(doc.engines),
                kind=doc.kind_of_page(page),
                page=page,
                section=sec,
                source=source,
                text=text,
            )
        )

    low_pages: list[int] = []
    for p in data["pages"]:
        page, text = p["page"], p["text"]
        if len(text.strip()) < LOW_TEXT_CHARS:
            low_pages.append(page)
            text = ocr_text.get(page, "").strip()
            source = SOURCE_OCR
        else:
            source = SOURCE_TEXT
        sec = section(page, p["text"] or text)
        for chunk in chunk_text(text):
            add(page, source, chunk, sec)

    n_tables = n_rows = 0
    for t in data["tables"]:
        page = t["page"]
        sec = section(page, data["pages"][page - 1]["text"])
        for rows in t["tables"]:
            n_tables += 1
            for chunk in chunk_text(_table_text(rows), max_chars=1200, overlap_lines=0):
                add(page, SOURCE_TABLE, chunk, sec)
        for r in t["fault_rows"]:
            n_rows += 1
            parts = [f"Неисправность: {r['symptom']}" if r["symptom"] else ""]
            parts += [f"Причина: {r['cause']}", f"Способ устранения: {r['remedy']}"]
            add(page, SOURCE_TABLE, "\n".join(p for p in parts if p), sec)

    passport = {
        "doc_id": doc.doc_id,
        "file": doc.file,
        "designation": doc.designation,
        "engines": list(doc.engines),
        "pages": len(data["pages"]),
        "low_text_pages": low_pages,
        "ocr_pages": sorted(p for p in low_pages if ocr_text.get(p, "").strip()),
        "printed_minus_pdf": data["offset"],
        "toc": [{"title": e.title, "printed_page": e.printed_page, "pdf_page": e.pdf_page} for e in toc],
        "tables": n_tables,
        "fault_rows": n_rows,
        "fragments": len(frags),
    }
    return frags, passport


# ---------- сборка ----------


def build_index(
    src: Path | None = None,
    out: Path | None = None,
    *,
    use_yandex: bool = True,
    echo: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Собрать индекс: PDF → текст/таблицы → OCR пустых страниц → фрагменты → BM25-токены → эмбеддинги."""
    from .yandex import EmbeddingClient, OcrClient, YandexConfig

    src = src or manuals_dir()
    out = out or index_dir()
    cache = out / "cache"
    missing = [d.file for d in DOCUMENTS if not (src / d.file).exists()]
    if missing:
        raise FileNotFoundError(f"нет PDF в {src}: {', '.join(missing)}")

    cfg = YandexConfig.from_env() if use_yandex else None
    if use_yandex and cfg is None:
        echo("YANDEX_API_KEY или YANDEX_FOLDER_ID не заданы: без OCR и поиска по смыслу")

    echo(f"Извлечение текста и таблиц из {len(DOCUMENTS)} PDF…")
    jobs = [(d.doc_id, str(src / d.file), str(cache / "extract")) for d in DOCUMENTS]
    with ProcessPoolExecutor(max_workers=min(len(jobs), os.cpu_count() or 2)) as pool:
        extracted = dict(zip([d.doc_id for d in DOCUMENTS], pool.map(_extract_job, jobs), strict=True))

    ocr = OcrClient(cfg, cache / "ocr") if cfg else None
    all_frags: list[Fragment] = []
    passports: list[dict[str, Any]] = []
    for doc in DOCUMENTS:
        data = extracted[doc.doc_id]
        ocr_text: dict[int, str] = {}
        low = [p["page"] for p in data["pages"] if len(p["text"].strip()) < LOW_TEXT_CHARS]
        if ocr and low:
            from .pdf import render_page_jpeg

            echo(f"  OCR {doc.doc_id}: {len(low)} стр.")
            for page in low:
                ocr_text[page] = ocr.recognize(render_page_jpeg(src / doc.file, page))
        frags, passport = fragments_for_document(doc, data, ocr_text)
        all_frags.extend(frags)
        passports.append(passport)
        echo(f"  {doc.doc_id}: {passport['pages']} стр., фрагментов {len(frags)}")

    echo("Токены BM25…")
    for f in all_frags:
        f.tokens = tokenize(f"{f.section}\n{f.text}")

    vectors: np.ndarray[Any, np.dtype[np.float32]] | None = None
    if cfg:
        echo(f"Эмбеддинги {len(all_frags)} фрагментов…")
        emb = EmbeddingClient(cfg, cache / "embeddings.jsonl")
        vecs = emb.embed(
            [f"{f.section}\n{f.text}" for f in all_frags],
            progress=lambda n: echo(f"  {n}/{len(all_frags)}"),
        )
        vectors = _normalize(np.asarray(vecs, dtype=np.float32))

    out.mkdir(parents=True, exist_ok=True)
    with (out / "fragments.jsonl").open("w", encoding="utf-8") as fh:
        for f in all_frags:
            fh.write(json.dumps(asdict(f), ensure_ascii=False) + "\n")
    vec_path = out / "vectors.npy"
    if vectors is not None:
        np.save(vec_path, vectors)
    elif vec_path.exists():
        vec_path.unlink()  # старые векторы не совпадут с новыми фрагментами
    meta = {"fragments": len(all_frags), "semantic": vectors is not None, "extract_version": EXTRACT_VERSION}
    (out / "passport.json").write_text(
        json.dumps({"meta": meta, "documents": passports}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    echo(f"Готово: {out} — фрагментов {len(all_frags)}, поиск по смыслу: {'да' if vectors is not None else 'нет'}")
    return {"meta": meta, "documents": passports}


def _normalize(m: np.ndarray[Any, np.dtype[np.float32]]) -> np.ndarray[Any, np.dtype[np.float32]]:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    out: np.ndarray[Any, np.dtype[np.float32]] = (m / norms).astype(np.float32)
    return out


def load_fragments(path: Path) -> list[Fragment]:
    return [Fragment(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
