"""HTTP-заглушка ВЫМЫШЛЕННОГО поставщика запчастей — только для демо нескольких поставщиков (`make parts-demo`).

GET /search?q=<обозначение или наименование> → {"items": [...]} из data/demo/parts_api_demo.json: точное обозначение
(без пробелов, точек и дефисов), иначе наименование содержит все слова запроса. Подключается файлом
data/demo/suppliers/02-demo-api.json, как настоящий поставщик. В сервис не входит: на стенде не запускается.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI

DATA = Path(__file__).resolve().parents[2] / "data" / "demo" / "parts_api_demo.json"
app = FastAPI(title="Демо-API поставщика запчастей (вымышленный)")


def _key(text: str) -> str:
    return re.sub(r"[\s.\-–]", "", text).casefold()


@app.get("/search")
def search(q: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = json.loads(DATA.read_text(encoding="utf-8"))["items"]
    exact = [i for i in items if i["article"] and _key(i["article"]) == _key(q)]
    words = q.casefold().split()
    named = [i for i in items if all(w in i["title"].casefold() for w in words)]
    return {"items": exact or named}
