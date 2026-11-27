"""Заглушки заказчика подключаются в процессе: тесты ходят в настоящие mock-приложения через TestClient.

Данные заглушек и парк (карточки ТС, ответы ML, справочник неисправностей) — материалы задачи; в git их нет
(указание организаторов 27.11), их приносит `make materials`. Без них тест, которому они нужны, пропускается
с причиной: и при сборке модуля, и при запуске. Остальные тесты идут как обычно. Пропускаем только
отсутствие файлов из `data/materials.lock.json` — любая другая ошибка остаётся ошибкой.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from service.clients import MLClient, ToirClient

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "neurodvs_mock"
sys.path.insert(0, str(VENDOR))

MATERIAL_PATHS = {
    str((ROOT / f["path"]).resolve())
    for f in json.loads((ROOT / "data" / "materials.lock.json").read_text(encoding="utf-8"))["files"]
}
MATERIALS_PRESENT = all(Path(p).is_file() for p in MATERIAL_PATHS)
NO_MATERIALS = "нет материалов задачи (парк и ответы ML вне git): make materials, ссылка — MATERIALS_URL"


def _missing_material(exc: BaseException | None) -> bool:
    """Исключение (или его причина) — отсутствие файла материалов задачи."""
    while exc is not None:
        if isinstance(exc, FileNotFoundError) and exc.filename and str(Path(exc.filename).resolve()) in MATERIAL_PATHS:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class _Module(pytest.Module):
    """Модуль, который читает парк при импорте, без материалов пропускается целиком, а не падает при сборке."""

    def _getobj(self) -> Any:
        try:
            return super()._getobj()
        except Exception as e:
            if not MATERIALS_PRESENT and _missing_material(e):
                raise pytest.skip.Exception(NO_MATERIALS, allow_module_level=True) from None
            raise


def pytest_pycollect_makemodule(module_path: Path, parent: pytest.Collector) -> pytest.Module | None:
    if MATERIALS_PRESENT or module_path.name == "conftest.py":
        return None
    return _Module.from_parent(parent, path=module_path)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Generator[None, Any, Any]:
    report = yield
    if not MATERIALS_PRESENT and report.failed and call.excinfo is not None and _missing_material(call.excinfo.value):
        report.outcome = "skipped"
        report.longrepr = (str(item.path), item.location[1] or 0, f"Skipped: {NO_MATERIALS}")
    return report


def _mock_apps() -> tuple[Any, Any]:
    if not MATERIALS_PRESENT:
        pytest.skip(NO_MATERIALS)
    from mock_ml.app import app as mock_ml_app
    from mock_toir.app import app as mock_toir_app

    return mock_ml_app, mock_toir_app


def __getattr__(name: str) -> Any:
    """`from conftest import mock_ml_app` в тестах — по-прежнему; заглушки загружаются при первом обращении."""
    if name in ("mock_ml_app", "mock_toir_app"):
        return _mock_apps()[name == "mock_toir_app"]
    raise AttributeError(name)


@pytest.fixture
def ml() -> MLClient:
    return MLClient(http=TestClient(_mock_apps()[0]))


@pytest.fixture
def toir() -> ToirClient:
    return ToirClient(http=TestClient(_mock_apps()[1]))


@pytest.fixture
def without_matrix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Как в CI: матрицы «код × двигатель» нет. Тесты поиска, заявки и проверки цифр на сценарии C1 (T792HO98, F02)
    написаны под ответ из фикстуры поиска; с настоящей матрицей ячейка F02 × ЯМЗ-236М2 подтверждена (реестр
    покрытия), и страницы и работы приходят из неё. Совместимость без матрицы — из её источника, как в CI."""
    from service import fault_matrix

    monkeypatch.setattr(fault_matrix, "matrix_path", lambda: tmp_path / "fault_matrix.json")
