"""HTTP-сервис: страница (/) и /health. Новые ручки добавлять сюда или в соседние модули."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from service import __version__

app = FastAPI(title="service", version=__version__)
INDEX_HTML = Path(__file__).parent / "static" / "index.html"


@app.get("/health")
def health() -> dict[str, Any]:
    """Сервис жив. Ключи не раскрываются — только факт их наличия."""
    return {
        "status": "ok",
        "version": __version__,
        "llm_key_present": bool(os.environ.get("LLM_API_KEY")),
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")
