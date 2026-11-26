"""Сверка THIRD_PARTY.md с pyproject.toml (Положение п. 4.4, 4.8, 9.1; CONSTRAINTS).

Каждая прямая Python-зависимость (runtime и dev) должна быть строкой таблицы в разделе
«## Python-зависимости» с непустой лицензией, и наоборот — в таблице нет лишних строк.
Код возврата 1 — расхождение.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

SECTION_RE = re.compile(r"^## Python-зависимости\s*$(.*?)(?=^## |\Z)", re.M | re.S)
NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared(pyproject: str) -> set[str]:
    data = tomllib.loads(pyproject)
    specs: list[str] = list(data.get("project", {}).get("dependencies", []))
    for group in data.get("dependency-groups", {}).values():
        specs.extend(s for s in group if isinstance(s, str))
    specs.extend(data.get("build-system", {}).get("requires", []))
    names = set()
    for spec in specs:
        match = NAME_RE.match(spec)
        if match:
            names.add(normalize(match.group(1)))
    return names


def listed(third_party: str) -> dict[str, str]:
    """Имя пакета → лицензия из таблицы раздела «Python-зависимости»."""
    match = SECTION_RE.search(third_party)
    if not match:
        return {}
    rows: dict[str, str] = {}
    for line in match.group(1).splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[0] or set(cells[0]) <= {"-", ":"} or cells[0] == "Пакет":
            continue
        rows[normalize(cells[0])] = cells[2]
    return rows


def check(root: Path) -> list[str]:
    deps = declared((root / "pyproject.toml").read_text(encoding="utf-8"))
    tp_path = root / "THIRD_PARTY.md"
    rows = listed(tp_path.read_text(encoding="utf-8")) if tp_path.exists() else {}
    errors = [f"нет в THIRD_PARTY.md: {name}" for name in sorted(deps - rows.keys())]
    errors += [f"лишняя строка в THIRD_PARTY.md (нет в pyproject): {name}" for name in sorted(rows.keys() - deps)]
    errors += [f"не указана лицензия: {name}" for name, lic in sorted(rows.items()) if name in deps and not lic]
    return errors


def main() -> int:
    errors = check(Path(__file__).resolve().parents[1])
    for err in errors:
        print(err, file=sys.stderr)
    if not errors:
        print("check_third_party: ок")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
