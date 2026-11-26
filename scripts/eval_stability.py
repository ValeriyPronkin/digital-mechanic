"""Стабильность ответов на открытую половину (штурман 26.11): у скольких вопросов одинаковые страницы и одинаковый
итог во всех прогонах eval-open с одним префиксом. Отчёты прогонов — reports/eval/<префикс>-<i>.json.

  make eval-stability PREFIX=stab-x RUNS=3     # прогнать RUNS раз и свести
  uv run python scripts/eval_stability.py stab-main stab-x   # свести уже сделанные прогоны
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

EVAL = Path(__file__).resolve().parents[1] / "reports" / "eval"


def load(label: str) -> dict[str, dict[str, Any]]:
    data = json.loads((EVAL / f"{label}.json").read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["results"]}


def summary(prefix: str) -> str:
    runs = []
    i = 1
    while (EVAL / f"{prefix}-{i}.json").exists():
        runs.append(load(f"{prefix}-{i}"))
        i += 1
    if not runs:
        return f"{prefix}: прогонов нет"
    ids = list(runs[0])
    n = len(runs)
    same_pages = sum(1 for q in ids if len({tuple(sorted(r[q].get("found_pages") or [])) for r in runs}) == 1)
    same_ok = sum(1 for q in ids if len({r[q]["ok"] for r in runs}) == 1)
    flaky = [q for q in ids if len({r[q]["ok"] for r in runs}) > 1]
    score = [sum(1 for q in ids if r[q]["ok"]) for r in runs]
    return (
        f"{prefix}: засчитано {score}; одинаковые страницы {n}/{n} — {same_pages}/{len(ids)}; "
        f"одинаковый итог {n}/{n} — {same_ok}/{len(ids)}; колеблются: {flaky}"
    )


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(summary(p))
