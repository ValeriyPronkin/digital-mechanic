"""Загрузка материалов задачи (scripts/materials.py) на синтетическом архиве: без сети наружу и без данных задачи.

Архив устроен как настоящий: папка верхнего уровня, вложенный zip заглушек и «PDF», который читать не нужно.
"""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

import materials

VEHICLES = b'{"vehicles": []}\n'
FAULTS = b'[{"code": "F00", "title": "synthetic"}]\n'
PDF = b"%PDF-1.4 " + b"x" * 300_000  # большой член архива: при чтении кусками его не качаем


def entry(path: str, member: str, data: bytes) -> dict[str, object]:
    return {"path": path, "member": member, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def make_archive() -> bytes:
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("mock_x/data/vehicles.json", VEHICLES)
        z.writestr("mock_x/data/fault_types.json", FAULTS)
        z.writestr("mock_x/mock_ml/app.py", "print()")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("materials/manual.pdf", PDF)
        z.writestr("materials/mock_x.zip", inner.getvalue())
    return outer.getvalue()


@pytest.fixture
def lock(tmp_path: Path) -> Path:
    path = tmp_path / "lock.json"
    files = [
        entry("data/vehicles.json", "mock_x/data/vehicles.json", VEHICLES),
        entry("data/fault_types.json", "mock_x/data/fault_types.json", FAULTS),
        entry("vendor/m/data/vehicles.json", "mock_x/data/vehicles.json", VEHICLES),
    ]
    path.write_text(json.dumps({"files": files}), encoding="utf-8")
    return path


class Server(http.server.BaseHTTPRequestHandler):
    body = b""
    ranges = True
    seen: ClassVar[list[str]] = []
    auth: ClassVar[list[str | None]] = []

    def do_GET(self) -> None:
        type(self).seen.append(self.headers.get("Range") or "")
        type(self).auth.append(self.headers.get("Authorization"))
        rng = self.headers.get("Range")
        if self.ranges and rng:
            start, _, end = rng.removeprefix("bytes=").partition("-")
            a, b = int(start), min(int(end), len(self.body) - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(self.body)}")
            chunk = self.body[a : b + 1]
        else:
            self.send_response(200)
            chunk = self.body
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def server() -> Iterator[tuple[str, type[Server]]]:
    handler = type("H", (Server,), {"body": make_archive(), "seen": [], "auth": []})
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/secret-path/archive.zip?key=SECRET", handler
    httpd.shutdown()


def run(monkeypatch: pytest.MonkeyPatch, url: str | None, *args: str, token: str | None = None) -> int:
    for name, value in (("MATERIALS_URL", url), ("MATERIALS_TOKEN", token)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return materials.main(list(args))


def test_lock_holds_no_content() -> None:
    """В git — только пути, размеры и хеши: ни одного значения длиннее хеша."""
    data = json.loads(materials.LOCK.read_text(encoding="utf-8"))
    for f in data["files"]:
        assert set(f) == {"path", "member", "size", "sha256"} and len(f["sha256"]) == 64


def test_no_url_is_a_clear_error(
    tmp_path: Path, lock: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(monkeypatch, None, "--lock", str(lock), "--root", str(tmp_path)) == 2
    assert "MATERIALS_URL не задан" in capsys.readouterr().err


def test_local_archive_nested_zip_and_idempotent(tmp_path: Path, lock: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "a.zip"
    archive.write_bytes(make_archive())
    root = tmp_path / "repo"
    assert run(monkeypatch, str(archive), "--lock", str(lock), "--root", str(root)) == 0
    assert (root / "data/vehicles.json").read_bytes() == VEHICLES
    assert (root / "vendor/m/data/vehicles.json").read_bytes() == VEHICLES
    assert not list(root.rglob("*.pdf")) and not (root / "data/app.py").exists()  # только файлы из замка
    # второй раз сеть не нужна: ссылки нет, а файлы сверены с замком
    assert run(monkeypatch, None, "--lock", str(lock), "--root", str(root)) == 0
    assert run(monkeypatch, None, "--check", "--lock", str(lock), "--root", str(root)) == 0


def test_hash_mismatch_is_refused(tmp_path: Path, lock: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["files"][0]["sha256"] = "0" * 64
    lock.write_text(json.dumps(data), encoding="utf-8")
    archive = tmp_path / "a.zip"
    archive.write_bytes(make_archive())
    root = tmp_path / "repo"
    assert run(monkeypatch, str(archive), "--lock", str(lock), "--root", str(root)) == 1
    assert not (root / "data/vehicles.json").exists()  # не совпало с замком — не записано


def test_http_range_reads_only_what_is_needed(
    tmp_path: Path,
    lock: Path,
    monkeypatch: pytest.MonkeyPatch,
    server: tuple[str, type[Server]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    url, handler = server
    root = tmp_path / "repo"
    assert run(monkeypatch, url, "--lock", str(lock), "--root", str(root), token="tok") == 0  # noqa: S106 — тестовый токен
    assert (root / "data/fault_types.json").read_bytes() == FAULTS
    fetched = 0
    for r in handler.seen:
        a, _, b = r.removeprefix("bytes=").partition("-")
        fetched += int(b) - int(a) + 1
    assert fetched < len(PDF) / 2  # «PDF» не скачан
    assert set(handler.auth) == {"Bearer tok"}
    err = capsys.readouterr().err
    assert "SECRET" not in err and "secret-path" not in err  # ссылка в журнале — только схема и хост


def test_http_without_range_downloads_whole(
    tmp_path: Path, lock: Path, monkeypatch: pytest.MonkeyPatch, server: tuple[str, type[Server]]
) -> None:
    url, handler = server
    handler.ranges = False
    root = tmp_path / "repo"
    assert run(monkeypatch, url, "--lock", str(lock), "--root", str(root)) == 0
    assert (root / "vendor/m/data/vehicles.json").read_bytes() == VEHICLES


def test_run_uses_fallback_and_sets_env(tmp_path: Path, lock: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Точка входа образа: в образе файлов нет → скачать в fallback, путь — в переменную, затем exec."""
    archive = tmp_path / "a.zip"
    archive.write_bytes(make_archive())
    seen: dict[str, object] = {}

    def fake_exec(cmd: str, argv: list[str]) -> None:
        seen["argv"] = argv
        seen["env"] = materials.os.environ["MOCK_DATA_PATH"]

    monkeypatch.setattr(materials.os, "execvp", fake_exec)
    monkeypatch.delenv("MOCK_DATA_PATH", raising=False)
    fallback = tmp_path / "tmp-materials"
    args = ["run", "--lock", str(lock), "--root", str(tmp_path / "image"), "--only", "vendor/m/data/"]
    args += ["--strip", "vendor/m/", "--fallback", str(fallback), "--env", "MOCK_DATA_PATH={dir}/vehicles.json"]
    run(monkeypatch, str(archive), *args, "--", "uvicorn", "app")
    assert seen["argv"] == ["uvicorn", "app"]
    assert seen["env"] == f"{fallback}/data/vehicles.json"
    assert (fallback / "data/vehicles.json").read_bytes() == VEHICLES
