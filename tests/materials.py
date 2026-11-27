"""Материалы задачи (заглушки заказчика и данные парка) — не в git, их кладёт `make fetch-materials` (п. 9.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "neurodvs_mock"
FILES = (
    VENDOR / "mock_ml" / "app.py",
    VENDOR / "mock_toir" / "app.py",
    ROOT / "data" / "vehicles.json",
    ROOT / "data" / "fault_types.json",
)
PRESENT = all(p.exists() for p in FILES)
REASON = "нет материалов задачи — make fetch-materials (TASK_MATERIALS_URL), п. 9.1"


def require() -> None:
    """Модуль читает парк или справочник при импорте: без материалов — пропустить модуль целиком (и те, что
    импортируют из него)."""
    if not PRESENT:
        pytest.skip(REASON, allow_module_level=True)
