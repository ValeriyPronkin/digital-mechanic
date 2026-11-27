"""Укоротить цитаты руководств в `data/contradictions.json` до QUOTE_MAX_WORDS слов подряд (issue #96).

Организаторы 26.11: текста руководств в открытом репозитории и его истории быть не должно. Цитата здесь — ссылка
на страницу, а не выгрузка. Отрывок берётся из самой цитаты, поэтому стоит на той же странице, и
`contradictions.verified_quotes` проходит как раньше. Повторный запуск ничего не меняет.

`data/fault_matrix.json` этот скрипт не трогает: цитаты работ и мер безопасности в ней — текст строк заявки, их
не укорачивают; сама матрица — часть базы знаний и уходит из репозитория вместе с индексом (#96, шаг 2).

    uv run python scripts/trim_quotes.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from service.fault_matrix import QUOTE_MAX_WORDS, trim_quote

ROOT = Path(__file__).resolve().parent.parent
CONTRADICTIONS = ROOT / "data" / "contradictions.json"


def _trim(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: trim_quote(v, str(o.get("designation", ""))) if k == "quote" else _trim(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_trim(v) for v in o]
    return o


def main() -> int:
    known = json.loads(CONTRADICTIONS.read_text(encoding="utf-8"))
    CONTRADICTIONS.write_text(json.dumps(_trim(known), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"цитаты не длиннее {QUOTE_MAX_WORDS} слов: {CONTRADICTIONS.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
