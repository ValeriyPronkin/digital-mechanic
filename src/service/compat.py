"""Совместимость «код неисправности × двигатель» (CLAUDE.md, правило 5).

Если узла у двигателя нет (бензин на дизеле, турбина на атмосферном) — заявку не отправляем.
STUB: compat-table — таблица `data/compat.json` пока черновая; признак «неизвестно» (null) заявку не блокирует.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from service.fleet import DATA_DIR


@dataclass(frozen=True)
class Compat:
    ok: bool
    why: str  # пусто, если совместимо


@lru_cache(maxsize=1)
def _table(path: Path = DATA_DIR / "compat.json") -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def check(code: str, engine: str) -> Compat:
    t = _table()
    rule = t["requires"].get(code)
    traits = t["engines"].get(engine)
    if rule is None or traits is None:
        return Compat(True, "")
    for key, need in rule.items():
        if key == "why":
            continue
        have = traits.get(key)
        if have is not None and have != need:
            return Compat(False, str(rule["why"]))
    return Compat(True, "")


def is_compatible(code: str, engine: str) -> bool:
    return check(code, engine).ok
