"""Заглушки заказчика подключаются в процессе: тесты ходят в настоящие mock-приложения через TestClient."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "neurodvs_mock"
sys.path.insert(0, str(VENDOR))

from mock_ml.app import app as mock_ml_app  # noqa: E402
from mock_toir.app import app as mock_toir_app  # noqa: E402

from service.clients import MLClient, ToirClient  # noqa: E402


@pytest.fixture
def ml() -> MLClient:
    return MLClient(http=TestClient(mock_ml_app))


@pytest.fixture
def toir() -> ToirClient:
    return ToirClient(http=TestClient(mock_toir_app))


@pytest.fixture
def without_matrix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Как в CI: матрицы «код × двигатель» нет. Тесты поиска, заявки и проверки цифр на сценарии C1 (T792HO98, F02)
    написаны под ответ из фикстуры поиска; с настоящей матрицей ячейка F02 × ЯМЗ-236М2 подтверждена (реестр
    покрытия), и страницы и работы приходят из неё. Совместимость без матрицы — из её источника, как в CI."""
    from service import fault_matrix

    monkeypatch.setattr(fault_matrix, "matrix_path", lambda: tmp_path / "fault_matrix.json")
