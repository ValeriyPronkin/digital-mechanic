"""Yandex Cloud: OCR (Vision) и эмбеддинги — с кэшем на диске.

Ключ — YANDEX_API_KEY, каталог — YANDEX_FOLDER_ID. Сюда уходят только страницы и фрагменты
руководств (материалы для базы знаний, задача #3), не данные ТС и не ответы ML.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

OCR_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
EMB_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
DOC_MODEL = "text-search-doc"
QUERY_MODEL = "text-search-query"
EMB_MAX_CHARS = 6000  # модель берёт до 2048 токенов; русский текст ~3 символа на токен


@dataclass(frozen=True)
class YandexConfig:
    api_key: str
    folder_id: str

    @classmethod
    def from_env(cls) -> YandexConfig | None:
        key = os.environ.get("YANDEX_API_KEY", "").strip()
        folder = os.environ.get("YANDEX_FOLDER_ID", "").strip()
        return cls(key, folder) if key and folder else None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Api-Key {self.api_key}", "x-folder-id": self.folder_id}


def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _post_with_retry(
    client: httpx.Client, url: str, payload: dict[str, Any], headers: dict[str, str], attempts: int = 8
) -> dict[str, Any]:
    delay = 1.0
    for attempt in range(attempts):
        try:
            r = client.post(url, json=payload, headers=headers)
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
        else:
            if r.status_code == 200:
                data: dict[str, Any] = r.json()
                return data
            if r.status_code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise RuntimeError(f"Yandex API {url}: HTTP {r.status_code}: {r.text[:300]}")
        time.sleep(delay)
        delay = min(delay * 2, 20)
    raise RuntimeError("unreachable")


class RateLimiter:
    """Не чаще rate запросов в секунду на все потоки (квота эмбеддингов Yandex — 10 в секунду)."""

    def __init__(self, rate: float) -> None:
        self.interval = 1.0 / rate
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        if slot > now:
            time.sleep(slot - now)


class OcrClient:
    """OCR страницы. Кэш: <cache_dir>/<sha256 изображения>.txt — повторная сборка не платит."""

    def __init__(self, cfg: YandexConfig, cache_dir: Path) -> None:
        self.cfg = cfg
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    def recognize(self, jpeg: bytes) -> str:
        key = hashlib.sha256(jpeg).hexdigest()
        path = self.cache_dir / f"{key}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
        payload = {
            "content": base64.b64encode(jpeg).decode("ascii"),
            "mimeType": "JPEG",
            "languageCodes": ["ru", "en"],
            "model": "page",
        }
        with httpx.Client(timeout=90) as client:
            data = _post_with_retry(client, OCR_URL, payload, self.cfg.headers)
        text = str(data.get("result", {}).get("textAnnotation", {}).get("fullText", ""))
        path.write_text(text, encoding="utf-8")
        return text


class EmbeddingClient:
    """Эмбеддинги Yandex: документы и запросы — разные модели. Кэш: JSONL «sha → вектор», дописывается."""

    def __init__(self, cfg: YandexConfig, cache_path: Path, workers: int = 8, rate: float = 8.0) -> None:
        self.cfg = cfg
        self.limiter = RateLimiter(rate)
        self.cache_path = cache_path
        self.workers = workers
        self._lock = threading.Lock()
        self._cache: dict[str, list[float]] = {}
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._cache[rec["k"]] = rec["v"]

    def _uri(self, model: str) -> str:
        return f"emb://{self.cfg.folder_id}/{model}/latest"

    def _one(self, client: httpx.Client, model: str, text: str) -> list[float]:
        key = _sha(model, text)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit
        self.limiter.wait()
        data = _post_with_retry(
            client, EMB_URL, {"modelUri": self._uri(model), "text": text[:EMB_MAX_CHARS]}, self.cfg.headers
        )
        vec = [float(x) for x in data["embedding"]]
        with self._lock:
            self._cache[key] = vec
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"k": key, "v": vec}) + "\n")
        return vec

    def embed(
        self, texts: Sequence[str], model: str = DOC_MODEL, progress: Callable[[int], None] | None = None
    ) -> list[list[float]]:
        """Пакет текстов параллельно (workers потоков); порядок результатов = порядок текстов."""
        with httpx.Client(timeout=30) as client, ThreadPoolExecutor(self.workers) as pool:
            futures = [pool.submit(self._one, client, model, t) for t in texts]
            out: list[list[float]] = []
            for i, fut in enumerate(futures):
                out.append(fut.result())
                if progress and (i + 1) % 200 == 0:
                    progress(i + 1)
            return out

    def embed_query(self, text: str) -> list[float]:
        with httpx.Client(timeout=15) as client:
            return self._one(client, QUERY_MODEL, text)
