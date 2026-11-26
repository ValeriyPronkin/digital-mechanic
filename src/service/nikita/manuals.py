"""Переходник: руководства двигателя для кода Никиты — из нашего каталога (`service.manuals.catalog`).
У Никиты это `app/manuals.py`; id руководств совпадают."""

from __future__ import annotations

from pathlib import Path

from service.manuals.catalog import DOCS_BY_ID, Document, documents_for_engine

ROOT = Path(__file__).resolve().parents[3]


class Manual:
    def __init__(self, doc: Document) -> None:
        self.id = doc.doc_id
        self.pages = doc.pages
        self.engines = doc.engines


def manuals_for(engine_model: str) -> tuple[Manual, ...]:
    return tuple(Manual(d) for d in documents_for_engine(engine_model))


BY_ID = {doc_id: Manual(d) for doc_id, d in DOCS_BY_ID.items()}
