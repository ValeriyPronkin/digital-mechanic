"""Интерфейс v2 (#52): сборка web/ раздаётся по /v2; маршруты приложения — index.html; за каталог сборки не выйти."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service import main


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text('<div id="root"></div><script src="/v2/assets/app.js"></script>')
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("нельзя")
    monkeypatch.setattr(main, "WEB_DIST", tmp_path)
    return tmp_path


def test_v2_serves_index_and_assets(dist: Path) -> None:
    c = TestClient(main.app)
    for path in ("/v2", "/v2/", "/v2/some/route"):
        r = c.get(path)
        assert r.status_code == 200 and 'id="root"' in r.text and r.headers["cache-control"] == "no-cache"
    a = c.get("/v2/assets/app.js")
    assert a.text == "console.log(1)" and "immutable" in a.headers["cache-control"]


def test_v2_cannot_escape_dist(dist: Path) -> None:
    r = TestClient(main.app).get("/v2/../secret.txt")
    assert "нельзя" not in r.text
    r = TestClient(main.app).get("/v2/%2e%2e/secret.txt")
    assert "нельзя" not in r.text


def test_v2_without_build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "WEB_DIST", tmp_path / "nothing")
    r = TestClient(main.app).get("/v2")
    assert r.status_code == 404 and "make web" in r.json()["detail"]


def test_old_page_untouched() -> None:
    r = TestClient(main.app).get("/")
    assert r.status_code == 200 and "Цифровой механик" in r.text
