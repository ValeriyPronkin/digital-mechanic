"""Сверка заглушек: каждая метка `STUB: <id>` в коде описана в разделе «Ограничения» README.

CONSTRAINTS: «каждая заглушка в коде помечена STUB:, CI сверяет список». Обратное не требуется:
README может перечислять ручные шаги и ограничения, у которых нет кода (D-15).
Код возврата 1 — есть незадокументированные заглушки.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MARK = "STUB" + ":"  # склеено, чтобы сам скрипт не считался заглушкой
STUB_RE = re.compile(re.escape(MARK) + r"\s*([a-z0-9][a-z0-9-]*)")
SECTION_RE = re.compile(r"^## Ограничения\s*$(.*?)(?=^## |\Z)", re.M | re.S)
SKIP_SUFFIXES = {".md", ".db", ".csv", ".lock", ".pem"}
SKIP_PREFIXES = ("tests/", "task/", "eval/", "kb/")


def code_stubs(root: Path, files: list[str]) -> dict[str, list[str]]:
    """id заглушки → где встречается (файл:строка)."""
    found: dict[str, list[str]] = {}
    for rel in files:
        if rel.startswith(SKIP_PREFIXES) or Path(rel).suffix in SKIP_SUFFIXES:
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for stub_id in STUB_RE.findall(line):
                found.setdefault(stub_id, []).append(f"{rel}:{lineno}")
    return found


def readme_stubs(readme: str) -> set[str]:
    match = SECTION_RE.search(readme)
    return set(STUB_RE.findall(match.group(1))) if match else set()


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(  # фиксированная команда без пользовательского ввода
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def check(root: Path) -> list[str]:
    readme_path = root / "README.md"
    documented = readme_stubs(readme_path.read_text(encoding="utf-8")) if readme_path.exists() else set()
    errors = []
    for stub_id, places in sorted(code_stubs(root, tracked_files(root)).items()):
        if stub_id not in documented:
            errors.append(f"{MARK} {stub_id} нет в README «Ограничения»: {', '.join(places)}")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = check(root)
    for err in errors:
        print(err, file=sys.stderr)
    if not errors:
        print("check_stubs: ок")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
