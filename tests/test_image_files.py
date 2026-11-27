"""Образ сервиса несёт всё, что сервис читает с диска (стенд 27.11: без registry/ «можно ли ехать» обрывался)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _copied() -> set[str]:
    """Каталоги и файлы корня репозитория, которые Dockerfile кладёт в итоговый образ (без стадии сборки web)."""
    final = ROOT.joinpath("Dockerfile").read_text(encoding="utf-8").rsplit("\nFROM ", 1)[1]
    out: set[str] = set()
    for line in final.splitlines():
        m = re.match(r"COPY\s+(?!--from)(.+)\s+\S+$", line.strip())
        if m:
            out |= {p.rstrip("/").split("/")[0] for p in m.group(1).split()}
    return out


def _read_from_root() -> set[str]:
    """Каталоги корня, которые код сервиса читает по пути от корня репозитория (`ROOT / "…"`, `parents[N] / "…"`)."""
    used: set[str] = set()
    for py in (ROOT / "src" / "service").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        used |= set(re.findall(r'(?:ROOT|parents\[\d\])\s*/\s*"([\w.-]+)"', text))
    return used


def test_dockerfile_copies_every_dir_the_service_reads() -> None:
    # web — собирается отдельной стадией; .git — версия из --build-arg; docs — только для тестов (copy_lint)
    not_in_image = {"web", ".git", "docs"}
    missing = _read_from_root() - _copied() - not_in_image
    assert not missing, f"сервис читает с диска, а Dockerfile не копирует: {sorted(missing)}"


def test_registry_is_copied() -> None:
    assert "registry" in _copied() and (ROOT / "registry" / "coverage.yaml").exists()
