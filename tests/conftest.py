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
