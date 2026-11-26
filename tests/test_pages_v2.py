"""Страницы руководства для просмотрщика v2 (#52 часть 3): картинка из бакета pages/, только руководства двигателя."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from service import api_v2, main
from service.clients import MLClient, ToirClient
from service.pages import PageImages
from test_agent import make_agent

WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 fake"


class Bucket:
    def __init__(self) -> None:
        self.reads = 0
        self.objects = {
            "pages/manifest.json": json.dumps({"yamz-236-rk": {"pages": 287, "dpi": 120}}).encode(),
            "pages/yamz-236-rk/270.webp": WEBP,
        }

    def get(self, key: str) -> bytes:
        self.reads += 1
        if key not in self.objects:
            raise RuntimeError("404")
        return self.objects[key]


def test_page_image_from_bucket_and_cached() -> None:
    b = Bucket()
    images = PageImages(b)
    assert images.get("yamz-236-rk", 270) == WEBP
    reads = b.reads
    assert images.get("yamz-236-rk", 270) == WEBP and b.reads == reads  # второй раз — из памяти
    assert images.get("yamz-236-rk", 999) is None  # вне документа — бакет не спрашиваем


@pytest.fixture
def client(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, PageImages]:
    ag, _ = make_agent([], ml, toir)
    images = PageImages(Bucket())
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(
            lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore(), None, lambda: images
        )
    )
    return TestClient(app), images


def test_page_view_only_for_engine_manuals(client: tuple[TestClient, PageImages]) -> None:
    c, _ = client
    vid = "M333YK47"  # ЯМЗ-236М2
    ok: dict[str, Any] = c.get(f"/api/v2/vehicles/{vid}/pages/yamz-236-rk/270").json()
    assert ok["image"] == "/manuals/yamz-236-rk/page/270.webp" and ok["page"] == 270 and ok["pages"] >= 270
    assert ok["short"].startswith("РК") and ok["marks"] == []
    foreign = c.get(f"/api/v2/vehicles/{vid}/pages/zmz-409-rk/10")
    assert foreign.status_code == 404  # правило 3: чужое руководство не открыть
    assert c.get(f"/api/v2/vehicles/{vid}/pages/yamz-236-rk/99999").status_code == 404


def test_page_view_without_image_still_has_page(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("service.manual_search.manual_pdf", lambda doc: None)
    ag, _ = make_agent([], ml, toir)
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(
            lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore(), None, lambda: PageImages()
        )
    )
    view = TestClient(app).get("/api/v2/vehicles/M333YK47/pages/yamz-236-rk/31").json()
    assert view["image"] is None and view["page"] == 31  # просмотрщик покажет текст страницы


def test_webp_route(monkeypatch: pytest.MonkeyPatch) -> None:
    images = PageImages(Bucket())
    monkeypatch.setattr(main, "page_images", lambda: images)
    c = TestClient(main.app)
    r = c.get("/manuals/yamz-236-rk/page/270.webp")
    assert r.status_code == 200 and r.content == WEBP and r.headers["content-type"] == "image/webp"
    assert "max-age=86400" in r.headers["cache-control"]
    monkeypatch.setattr("service.manual_search.manual_pdf", lambda doc: None)
    assert c.get("/manuals/yamz-236-rk/page/5.webp").status_code == 404
