"""Выкладка индекса: состав файлов, манифест и версия по содержимому (без сети)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from index_upload import build_manifest, index_files


def _index(root: Path, fragments: str = "a\n") -> None:
    (root / "cache" / "ocr").mkdir(parents=True)
    (root / "cache" / "extract").mkdir()
    (root / "fragments.jsonl").write_text(fragments, encoding="utf-8")
    (root / "passport.json").write_text(json.dumps({"meta": {"fragments": 1}}), encoding="utf-8")
    (root / "cache" / "ocr" / "x.txt").write_text("ocr", encoding="utf-8")
    (root / "cache" / "extract" / "big.json").write_text("{}", encoding="utf-8")


def test_index_files_skip_extract_cache(tmp_path: Path) -> None:
    _index(tmp_path)
    assert index_files(tmp_path) == ["fragments.jsonl", "passport.json", "cache/ocr/x.txt"]


def test_index_files_require_built_index(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="make index"):
        index_files(tmp_path)


def test_version_depends_on_content_only(tmp_path: Path) -> None:
    when = datetime(2026, 11, 26, tzinfo=UTC)
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    _index(a)
    _index(b)
    _index(c, fragments="другое\n")
    ma = build_manifest(a, index_files(a), when)
    assert ma["version"] == build_manifest(b, index_files(b), when)["version"]
    assert ma["version"] != build_manifest(c, index_files(c), when)["version"]
    assert ma["version"].startswith("20261126-")
    assert ma["files"]["fragments.jsonl"]["size"] == 2
    assert ma["meta"] == {"fragments": 1}
