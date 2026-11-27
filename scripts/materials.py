"""Материалы задачи вне git: скачать архив по MATERIALS_URL, сверить с замком и разложить по местам.

Указание организаторов 27.11: данные заглушек (ответы диагностики, карточки ТС) и PDF не коммитим,
на стенде загружаем при развёртывании по ссылке из материалов задачи, саму ссылку держим в переменной
окружения. В git — только замок `data/materials.lock.json`: пути, размеры и SHA-256, без содержимого.

    python scripts/materials.py              # make materials: недостающие файлы → их места в репозитории
    python scripts/materials.py --check      # только сверить с замком, без сети; код 1 — чего-то нет
    python scripts/materials.py run --only data/ --env DATA_DIR={dir} -- uvicorn ...   # точка входа образа

Ссылка — MATERIALS_URL: прямая ссылка на архив (zip) материалов, публичная ссылка Яндекс Диска или
путь к уже скачанному архиву. Нужные файлы ищутся в архиве и во вложенных zip (заглушки лежат во вложенном
`neurodvs_hackathon_mock_*.zip`). Если сервер отдаёт куски файла (Range), читаются только оглавление
архива и нужный вложенный zip — десятки килобайт вместо всего архива с PDF. MATERIALS_TOKEN (необязательно) —
заголовок Authorization, только для хоста из ссылки. Ссылку в журнал не пишем: только схему и хост.

Повторный запуск ничего не скачивает, если файлы на месте и совпадают с замком.
Зависимости — только стандартная библиотека: скрипт работает и в образе заглушек.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "data" / "materials.lock.json"
YADISK_HOSTS = {"disk.yandex.ru", "disk.yandex.com", "disk.yandex.kz", "yadi.sk", "disk.360.yandex.ru"}
YADISK_API = "https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key="
NESTED_ZIP_MAX = 64 * 1024 * 1024  # вложенный архив больше — не наш (там PDF), не читаем
BLOCK = 256 * 1024
TIMEOUT = 60
ATTEMPTS = 3


class MaterialsError(Exception):
    """Понятная ошибка для человека; код возврата 1 (2 — не задана ссылка)."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Entry:
    path: str  # путь в репозитории
    member: str  # путь внутри архива заглушек
    size: int
    sha256: str


def log(msg: str) -> None:
    print(f"materials: {msg}", file=sys.stderr, flush=True)


def load_lock(lock: Path) -> list[Entry]:
    data = json.loads(lock.read_text(encoding="utf-8"))
    return [Entry(f["path"], f["member"], int(f["size"]), f["sha256"]) for f in data["files"]]


def target(entry: Entry, root: Path, strip: str) -> Path:
    rel = entry.path.removeprefix(strip) if strip else entry.path
    return root / rel


def matches(data: bytes, entry: Entry) -> bool:
    return len(data) == entry.size and hashlib.sha256(data).hexdigest() == entry.sha256


def is_in_place(path: Path, entry: Entry) -> bool:
    return path.is_file() and path.stat().st_size == entry.size and matches(path.read_bytes(), entry)


def safe_url(url: str) -> str:
    """Схема и хост, без пути и параметров: в ссылке может быть ключ доступа."""
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.hostname}/…" if p.scheme and p.hostname else "<локальный файл>"


# --- скачивание ---------------------------------------------------------------------------------------------


def _request(url: str, token: str | None, token_host: str | None, extra: dict[str, str] | None = None) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "materials-fetch/1", **(extra or {})})  # noqa: S310
    if token and urllib.parse.urlsplit(url).hostname == token_host:
        # «unredirected» — при переадресации на другой хост токен не уходит
        req.add_unredirected_header("Authorization", token if " " in token else f"Bearer {token}")
    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            return urllib.request.urlopen(req, timeout=TIMEOUT)  # noqa: S310 — схему проверяем в resolve()
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise MaterialsError(f"{safe_url(url)} ответил {e.code} {e.reason}: проверьте ссылку и токен") from None
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(2 * (attempt + 1))
    reason = getattr(last, "reason", None) or type(last).__name__
    raise MaterialsError(f"{safe_url(url)} не отвечает ({reason}) после {ATTEMPTS} попыток")


def resolve(url: str, token: str | None) -> str:
    """Публичная ссылка Яндекс Диска → прямая ссылка на скачивание; остальные — как есть."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise MaterialsError("MATERIALS_URL: нужна ссылка http(s) или путь к архиву")
    if parts.hostname in YADISK_HOSTS:
        with _request(YADISK_API + urllib.parse.quote(url, safe=""), None, None) as resp:
            href = json.loads(resp.read()).get("href")
        if not href:
            raise MaterialsError("Яндекс Диск не выдал ссылку на скачивание: ссылка публичная?")
        return str(href)
    return url


class HttpRangeFile(io.RawIOBase):
    """Файл на сервере, который отдаёт куски (Range): zipfile читает оглавление и нужные записи, не весь архив."""

    def __init__(self, url: str, size: int, token: str | None, token_host: str | None) -> None:
        self.url, self.size, self.token, self.token_host = url, size, token, token_host
        self.pos = 0
        self.requests = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence]
        self.pos = max(0, base + offset)
        return self.pos

    def readinto(self, b: Any) -> int:
        view = memoryview(b).cast("B")
        if self.pos >= self.size or not len(view):
            return 0
        end = min(self.pos + len(view), self.size) - 1
        self.requests += 1
        with _request(self.url, self.token, self.token_host, {"Range": f"bytes={self.pos}-{end}"}) as resp:
            if resp.status != 206:
                raise MaterialsError(f"{safe_url(self.url)} перестал отдавать куски файла (ответ {resp.status})")
            data = resp.read()
        view[: len(data)] = data
        self.pos += len(data)
        return len(data)


@dataclass
class Archive:
    file: IO[bytes]
    how: str  # для журнала


def open_archive(source: str, token: str | None, workdir: Path) -> Archive:
    """Архив материалов: локальный путь, кусками по Range или (если сервер не умеет) целиком во временный файл."""
    if "://" not in source or source.startswith("file://"):
        path = Path(urllib.parse.urlsplit(source).path if source.startswith("file://") else source).expanduser()
        if not path.is_file():
            raise MaterialsError("MATERIALS_URL: локальный архив не найден")
        return Archive(path.open("rb"), "локальный файл")
    token_host = urllib.parse.urlsplit(source).hostname
    url = resolve(source, token)
    with _request(url, token, token_host, {"Range": "bytes=0-0"}) as resp:
        final = resp.geturl()
        total = (resp.headers.get("Content-Range") or "").rpartition("/")[2]
        if resp.status == 206 and total.isdigit():
            raw = HttpRangeFile(final, int(total), token, token_host)
            return Archive(io.BufferedReader(raw, buffer_size=BLOCK), f"кусками из {safe_url(source)}")
        # Сервер отдал весь файл: сохраняем во временный файл (архив с PDF — около 150 МБ)
        tmp = tempfile.NamedTemporaryFile(dir=workdir, suffix=".zip", delete=False)
        size = 0
        with tmp:
            while chunk := resp.read(BLOCK):
                tmp.write(chunk)
                size += len(chunk)
        log(f"сервер не отдаёт куски файла — скачан весь архив, {size / 1e6:.1f} МБ")
        return Archive(Path(tmp.name).open("rb"), f"целиком из {safe_url(source)}")


def find(zf: zipfile.ZipFile, wanted: dict[str, Entry], depth: int = 0) -> Iterator[tuple[Entry, bytes]]:
    """Нужные записи архива по пути (с любым префиксом папки) и во вложенных zip."""
    for info in zf.infolist():
        name = info.filename
        hits = [e for e in wanted.values() if name == e.member or name.endswith("/" + e.member)]
        data = zf.read(info) if hits else b""
        for entry in hits:
            if matches(data, entry):
                del wanted[entry.path]
                yield entry, data
        if not wanted:
            return
        if depth < 2 and name.lower().endswith(".zip") and info.file_size <= NESTED_ZIP_MAX:
            with zipfile.ZipFile(io.BytesIO(zf.read(info))) as inner:
                yield from find(inner, wanted, depth + 1)
            if not wanted:
                return


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def fetch(entries: list[Entry], root: Path, strip: str, url: str | None, token: str | None) -> None:
    if not url:
        raise MaterialsError(
            "MATERIALS_URL не задан. Это ссылка на архив материалов задачи от организаторов; "
            "положите её в .env (README, «Запуск») или скачайте архив и укажите путь к нему",
            code=2,
        )
    wanted = {e.path: e for e in entries}
    with tempfile.TemporaryDirectory(prefix="materials-") as work:
        archive = open_archive(url, token, Path(work))
        log(f"архив: {archive.how}")
        try:
            with archive.file, zipfile.ZipFile(archive.file) as zf:
                for entry, data in find(zf, wanted):
                    write_atomic(target(entry, root, strip), data)
                    log(f"{entry.path} — на месте ({entry.size} байт, SHA-256 сверен)")
        except zipfile.BadZipFile:
            raise MaterialsError("по ссылке не zip-архив: нужна прямая ссылка на архив материалов задачи") from None
    if wanted:
        missing = ", ".join(e.path for e in wanted.values())
        raise MaterialsError(
            f"в архиве нет файлов, совпадающих с замком: {missing}. "
            "Ссылка не на те материалы, или организаторы их обновили — сверьте и обновите data/materials.lock.json"
        )


# --- команды ------------------------------------------------------------------------------------------------


def select(entries: list[Entry], only: str) -> list[Entry]:
    chosen = [e for e in entries if e.path.startswith(only)]
    if not chosen:
        raise MaterialsError(f"в замке нет файлов под {only!r}")
    return chosen


def ensure(entries: list[Entry], root: Path, strip: str, fallback: Path | None) -> Path:
    """Файлы на месте в root → root; иначе скачать (в fallback, если задан) → куда скачали."""
    if all(is_in_place(target(e, root, strip), e) for e in entries):
        return root
    dest = fallback or root
    missing = [e for e in entries if not is_in_place(target(e, dest, strip), e)]
    if missing:
        fetch(missing, dest, strip, os.environ.get("MATERIALS_URL"), os.environ.get("MATERIALS_TOKEN") or None)
    return dest


def common_dir(entries: list[Entry], root: Path, strip: str) -> Path:
    return Path(os.path.commonpath([target(e, root, strip).parent for e in entries]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", nargs="?", choices=["fetch", "run"], default="fetch")
    ap.add_argument("--lock", type=Path, default=LOCK)
    ap.add_argument("--root", type=Path, default=ROOT, help="куда класть (по умолчанию корень репозитория)")
    ap.add_argument("--only", default="", help="только файлы замка с этим префиксом пути")
    ap.add_argument("--strip", default="", help="отрезать этот префикс от пути при записи")
    ap.add_argument("--check", action="store_true", help="только сверить, без сети")
    ap.add_argument("--fallback", type=Path, help="run: если в --root нет файлов, скачать сюда")
    ap.add_argument("--env", action="append", default=[], help="run: NAME=шаблон, {dir} — папка с файлами")
    argv = sys.argv[1:] if argv is None else argv
    cut = argv.index("--") if "--" in argv else len(argv)
    args, cmd = ap.parse_args(argv[:cut]), argv[cut + 1 :]  # run: команда — всё после --
    try:
        entries = select(load_lock(args.lock), args.only)
        if args.check:
            bad = [e.path for e in entries if not is_in_place(target(e, args.root, args.strip), e)]
            for p in bad:
                log(f"{p} — нет или не совпадает с замком")
            if not bad:
                log(f"файлов на месте: {len(entries)} из {len(entries)}")
            return 1 if bad else 0
        if args.command == "fetch":
            ensure(entries, args.root, args.strip, None)
            log(f"файлов на месте: {len(entries)} из {len(entries)}")
            return 0
        if not cmd:
            raise MaterialsError("run: после -- нужна команда")
        where = ensure(entries, args.root, args.strip, args.fallback)
        folder = str(common_dir(entries, where, args.strip))
        for spec in args.env:
            name, _, template = spec.partition("=")
            os.environ[name] = template.replace("{dir}", folder)
    except MaterialsError as e:
        log(str(e))
        return e.code
    sys.stdout.flush()
    os.execvp(cmd[0], cmd)  # noqa: S606 — команда из Dockerfile, не внешний ввод


if __name__ == "__main__":
    sys.exit(main())
