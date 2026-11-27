"""Материалы задачи — не в git (ответ организаторов 27.11, п. 9.1 Положения): скачать по ссылке и разложить.

Источник — `TASK_MATERIALS_URL` (переменная окружения, в коде ссылки нет) или аргумент: ссылка http(s) на архив
(.zip, .tar.gz), публичная ссылка Яндекс Диска (файл или папка: из папки — только архив заглушек
`*mock*.zip` или `TASK_MATERIALS_PATH`) или локальный путь (архив или распакованный каталог).
Проверка целостности — `TASK_MATERIALS_SHA256` (необязательно; для локального каталога не применяется).
Только стандартная библиотека: запускается и в workflow без установки зависимостей (`python3 scripts/…`).

Куда (всё — в .gitignore):
  vendor/neurodvs_mock/      — заглушки Mock ML и Mock ТОиР с их данными, как в архиве;
  data/vehicles.json         — парк и история проверок (копия из заглушек: её читает сервис);
  data/fault_types.json      — справочник F01…F14 (то же).

    make fetch-materials                       # ссылка из TASK_MATERIALS_URL (.env или окружение)
    make fetch-materials MATERIALS=путь.zip    # уже скачанный архив
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "neurodvs_mock"
DATA = ROOT / "data"
COPIED = ("vehicles.json", "fault_types.json")
YADISK_HOSTS = {"disk.yandex.ru", "disk.yandex.com", "yadi.sk", "disk.360.yandex.ru"}
YADISK_RESOURCES = "https://cloud-api.yandex.net/v1/disk/public/resources"
YADISK_API = f"{YADISK_RESOURCES}/download"


def _get(url: str, timeout: float = 300) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "fetch-materials"})  # noqa: S310 — только http(s)
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — схема проверена в main()


def _yadisk_href(public_url: str) -> str:
    """Прямая ссылка на файл по публичной ссылке Диска. Папка материалов целиком — это и PDF (≈150 МБ):
    из папки берём только архив заглушек — `TASK_MATERIALS_PATH` или единственный `*mock*.zip` в корне папки."""
    query = {"public_key": public_url}
    with _get(f"{YADISK_RESOURCES}?{urlencode({**query, 'limit': 200})}", timeout=60) as r:
        meta = json.load(r)
    if meta.get("type") == "dir":
        path = os.environ.get("TASK_MATERIALS_PATH", "").strip()
        if not path:
            items = meta.get("_embedded", {}).get("items", [])
            zips = [i["path"] for i in items if i["type"] == "file" and re.search(r"mock.*\.zip$", i["name"], re.I)]
            if len(zips) != 1:
                raise SystemExit(
                    f"fetch-materials: в папке Диска архивов *mock*.zip — {len(zips)}; задайте TASK_MATERIALS_PATH"
                )
            path = zips[0]
        query["path"] = path
    with _get(f"{YADISK_API}?{urlencode(query)}", timeout=60) as r:
        return str(json.load(r)["href"])


def _download(url: str, dest: Path) -> None:
    host = urlparse(url).hostname or ""
    if host in YADISK_HOSTS:
        url = _yadisk_href(url)
    with _get(url) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    # саму ссылку не печатаем: она может быть закрытой
    print(f"скачано с {host}: {dest.stat().st_size / 1e6:.2f} МБ")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract(archive: Path, out: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:  # zipfile сам отбрасывает «..» и абсолютные пути
            z.extractall(out)  # noqa: S202 — zipfile нормализует пути сам
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            if hasattr(tarfile, "data_filter"):  # Python ≥ 3.11.4: без выхода за каталог, ссылок и спецфайлов
                t.extractall(out, filter="data")
            else:  # старый Python: только обычные файлы и каталоги с путями внутри out
                for m in t.getmembers():
                    target = (out / m.name).resolve()
                    if not (m.isfile() or m.isdir()) or not target.is_relative_to(out.resolve()):
                        raise SystemExit(f"fetch-materials: в архиве недопустимый элемент {m.name!r}")
                t.extractall(out)  # noqa: S202 — элементы проверены выше
    else:
        raise SystemExit(f"fetch-materials: {archive.name} — не zip и не tar")


def find_mock_root(tree: Path) -> Path:
    """Каталог заглушек — тот, где лежат mock_ml/app.py и mock_toir/app.py (на любой глубине архива)."""
    roots = sorted(
        {p.parent.parent for p in tree.rglob("mock_ml/app.py") if (p.parent.parent / "mock_toir" / "app.py").exists()}
    )
    if len(roots) != 1:
        raise SystemExit(f"fetch-materials: каталогов с mock_ml и mock_toir в материалах — {len(roots)}, нужен 1")
    return roots[0]


def find_data(tree: Path, mock_root: Path, name: str) -> Path:
    """Данные — рядом с заглушками (data/<name>); иначе единственный такой файл в материалах."""
    near = mock_root / "data" / name
    if near.exists():
        return near
    found = sorted(tree.rglob(name))
    if len(found) != 1:
        raise SystemExit(f"fetch-materials: {name} в материалах — {len(found)} шт., нужен 1")
    return found[0]


def install(tree: Path) -> dict[str, int]:
    mock_root = find_mock_root(tree)
    if mock_root.resolve().is_relative_to(VENDOR.resolve()):
        raise SystemExit("fetch-materials: источник — сам vendor/neurodvs_mock; укажите архив или другой каталог")
    sources = {name: find_data(tree, mock_root, name) for name in COPIED}
    vehicles = json.loads(sources["vehicles.json"].read_text(encoding="utf-8"))["vehicles"]
    faults = json.loads(sources["fault_types.json"].read_text(encoding="utf-8"))
    if VENDOR.exists():
        shutil.rmtree(VENDOR)
    shutil.copytree(
        mock_root, VENDOR, ignore=shutil.ignore_patterns("__pycache__", ".venv", "*.pyc", "._*", ".DS_Store")
    )
    for name, src in sources.items():
        shutil.copyfile(src, DATA / name)
    return {
        "машин": len(vehicles),
        "проверок": sum(len(v["sessions"]) for v in vehicles),
        "кодов": len(faults),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="ссылка или путь; по умолчанию — TASK_MATERIALS_URL")
    args = ap.parse_args(argv)
    source = (args.source or os.environ.get("TASK_MATERIALS_URL", "")).strip()
    if not source:
        print(
            "fetch-materials: не задан TASK_MATERIALS_URL (ссылка на материалы задачи от организаторов) — "
            "впишите её в .env или передайте MATERIALS=путь",
            file=sys.stderr,
        )
        return 2
    expected = os.environ.get("TASK_MATERIALS_SHA256", "").strip().lower()
    with tempfile.TemporaryDirectory(prefix="materials-") as tmp:
        tmp_dir = Path(tmp)
        local = Path(source).expanduser()
        if local.is_dir():
            tree = local
        else:
            archive = local if local.is_file() else tmp_dir / "materials.archive"
            if not local.is_file():
                if urlparse(source).scheme not in ("http", "https"):
                    print(f"fetch-materials: {source!r} — не ссылка http(s) и не путь к файлу", file=sys.stderr)
                    return 2
                try:
                    _download(source, archive)
                except (urllib.error.URLError, OSError, KeyError) as exc:  # ссылку не печатаем
                    why = getattr(exc, "code", "") or getattr(exc, "reason", "")
                    print(f"fetch-materials: не скачалось — {type(exc).__name__}: {why}",
                          file=sys.stderr)  # fmt: skip
                    return 1
            if expected and _sha256(archive) != expected:
                print("fetch-materials: SHA-256 архива не совпадает с TASK_MATERIALS_SHA256", file=sys.stderr)
                return 1
            tree = tmp_dir / "tree"
            _extract(archive, tree)
        counts = install(tree)
    print("fetch-materials: ок — " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print(f"  {VENDOR.relative_to(ROOT)}/, data/{COPIED[0]}, data/{COPIED[1]} (в git не входят)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
