"""Картинки страниц руководств для просмотрщика (#52 часть 3, `PageSheet` интерфейса v2; страницы — сессия 2).

Бакет: `pages/<doc_id>/<pdf_page>.webp` (страница PDF с 1) + `pages/manifest.json` ({doc_id: {pages, dpi, sizes}}).
Порядок: память экземпляра → бакет (на стенде по IAM-токену, локально по ключу из `.env`) → рендер из локального
PDF, если он есть (`MANUALS_DIR`). Нет ни того, ни другого — картинки нет, просмотрщик показывает текст страницы.
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
from collections import OrderedDict
from typing import Any

log = logging.getLogger(__name__)


class PageImages:
    MEMORY_ITEMS = 64  # ~100 КБ на страницу: ≈6 МБ в памяти экземпляра

    def __init__(self, bucket: Any = None) -> None:
        self.bucket = bucket
        self._mem: OrderedDict[tuple[str, int], bytes] = OrderedDict()
        self._manifest: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            data: dict[str, Any] = {}
            if self.bucket is not None:
                try:
                    data = json.loads(self.bucket.get("pages/manifest.json"))
                except Exception as exc:  # бакет недоступен — картинок нет, только текст
                    log.warning("pages/manifest.json не прочитан: %s", type(exc).__name__)
            self._manifest = data
        return self._manifest

    def pages(self, doc_id: str) -> int:
        return int((self.manifest().get(doc_id) or {}).get("pages") or 0)

    def available(self, doc_id: str, page: int) -> bool:
        if 1 <= page <= self.pages(doc_id):
            return True
        from service.manual_search import manual_pdf

        return manual_pdf(doc_id) is not None

    def get(self, doc_id: str, page: int) -> bytes | None:
        key = (doc_id, page)
        with self._lock:
            if key in self._mem:
                self._mem.move_to_end(key)
                return self._mem[key]
        data = self._from_bucket(doc_id, page) or self._from_pdf(doc_id, page)
        if data is not None:
            with self._lock:
                self._mem[key] = data
                while len(self._mem) > self.MEMORY_ITEMS:
                    self._mem.popitem(last=False)
        return data

    def _from_bucket(self, doc_id: str, page: int) -> bytes | None:
        if self.bucket is None or not 1 <= page <= self.pages(doc_id):
            return None
        try:
            data: bytes = self.bucket.get(f"pages/{doc_id}/{page}.webp")
            return data
        except Exception as exc:
            log.warning("pages/%s/%s.webp не прочитан: %s", doc_id, page, type(exc).__name__)
            return None

    @staticmethod
    def _from_pdf(doc_id: str, page: int) -> bytes | None:
        from service.manual_search import manual_pdf

        path = manual_pdf(doc_id)
        if path is None:
            return None
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            if not 1 <= page <= len(pdf):
                return None
            buf = io.BytesIO()
            pdf[page - 1].render(scale=120 / 72).to_pil().save(buf, format="WEBP", quality=80)
            return buf.getvalue()
        finally:
            pdf.close()

    @classmethod
    def from_env(cls) -> PageImages:
        """Бакет: локально — по ключу из `.env` (S3_ACCESS_KEY_ID), на стенде ключа нет — по IAM-токену."""
        name = os.environ.get("S3_BUCKET", "").strip()
        if not name:
            return cls()
        import httpx

        from service import kb_store

        http = httpx.Client(timeout=15)
        endpoint = os.environ.get("S3_ENDPOINT", kb_store.DEFAULT_ENDPOINT)
        key_id, secret = os.environ.get("S3_ACCESS_KEY_ID", ""), os.environ.get("S3_SECRET_ACCESS_KEY", "")
        if key_id and secret:
            return cls(kb_store.Bucket(name, kb_store.sigv4_auth(key_id, secret), http, endpoint))
        from service.spend import RefreshingIamAuth

        return cls(kb_store.Bucket(name, RefreshingIamAuth(http), http, endpoint))
