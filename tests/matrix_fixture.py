"""Матрица «код × двигатель» в тестах (#96, шаг 2).

Настоящая матрица — 450 цитат руководств, в git её нет: она лежит в INDEX_DIR (стенд скачивает её с индексом) или
локально в data/. Тесты, которым нужно её содержание, без неё пропускаются (`needs_matrix`), как тесты поиска без
индекса. Логика загрузки, пути и /health проверяется на синтетической матрице ниже: цитаты — не текст руководств,
не длиннее пяти слов.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from service.fault_matrix import matrix_loaded

NO_MATRIX = (
    "нет fault_matrix.json: матрица с цитатами руководств в git не входит (#96) — "
    "положите её в INDEX_DIR или data/ (make index, scripts/build_fault_matrix.py)"
)
needs_matrix = pytest.mark.skipif(not matrix_loaded(), reason=NO_MATRIX)


def _ref(doc: str, page: int, quote: str, **kw: Any) -> dict[str, Any]:
    return {"doc": doc, "page": page, "quote": quote, **kw}


# Две ячейки: «подтверждено» и «узла нет». Документы и страницы — существующие (иначе verify_cell их выбросит).
SYNTHETIC: dict[str, Any] = {
    "_comment": "Синтетическая матрица для тестов: цитаты выдуманы, не из руководств.",
    "cells": [
        {
            "code": "F01",
            "engine": "ЯМЗ-236М2",
            "status": "confirmed",
            "applicable": "true",
            "basis": _ref("yamz-236-rk", 10, "узел есть"),
            "pages": [_ref("yamz-236-rk", 10, "проверка узла", what="проверка")],
            "operations": [_ref("yamz-236-rk", 11, "Заменить деталь А", tools=["ключ"])],
            "spare_parts": [_ref("yamz-236-rk", 12, "Деталь А 000-0000000", designation="000-0000000")],
            "safety": [_ref("yamz-236-rk", 11, "Внимание: тестовое предупреждение")],
        },
        {
            "code": "F09",
            "engine": "ЗМЗ-5234.10",
            "status": "not_applicable",
            "applicable": "false",
            "basis": _ref("zmz-5234-rk", 3, "двигатель тестовый бензиновый"),
            "why": "узла нет",
            "pages": [],
            "operations": [],
            "spare_parts": [],
            "safety": [],
        },
    ],
}


def write_synthetic(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(SYNTHETIC, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
