"""Заглушки заказчика подключаются в процессе: тесты ходят в настоящие mock-приложения через TestClient.

Материалы задачи (заглушки, `data/vehicles.json`, `data/fault_types.json`) — не в git (п. 9.1 Положения): их кладёт
`make fetch-materials` по ссылке из `TASK_MATERIALS_URL`. Без них тесты, которым нужны заглушки или парк,
пропускаются с явной пометкой — и в итоге прогона строка, сколько пропущено.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from materials import PRESENT as MATERIALS
from materials import REASON as NO_MATERIALS
from materials import VENDOR

if MATERIALS:
    sys.path.insert(0, str(VENDOR))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if MATERIALS:
        return
    skip = pytest.mark.skip(reason=NO_MATERIALS)
    for item in items:
        if item.get_closest_marker("materials") or {"ml", "toir"} & set(getattr(item, "fixturenames", ())):
            item.add_marker(skip)


def pytest_terminal_summary(terminalreporter: Any) -> None:
    """Явная строка в конце прогона: сколько тестов и модулей пропущено без материалов."""
    n = sum(NO_MATERIALS in str(r.longrepr) for r in terminalreporter.stats.get("skipped", []))
    if n:
        terminalreporter.write_line(
            f"ВНИМАНИЕ: пропущено {n} (тестов и модулей) — {NO_MATERIALS}", yellow=True, bold=True
        )


@pytest.fixture
def ml() -> Any:
    from fastapi.testclient import TestClient
    from mock_ml.app import app

    from service.clients import MLClient

    return MLClient(http=TestClient(app))


@pytest.fixture
def toir() -> Any:
    from fastapi.testclient import TestClient
    from mock_toir.app import app

    from service.clients import ToirClient

    return ToirClient(http=TestClient(app))
