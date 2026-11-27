"""Индекс руководств и PDF в частном бакете Object Storage (D-9, issue #6).

Раскладка бакета `S3_BUCKET`:
  manuals/<файл PDF>            — PDF заказчика (выкладываются из локальной сессии, стенд их не качает);
  index/<версия>/<файл>         — собранный индекс без кэша извлечения (FILES);
  index/<версия>/MANIFEST.json  — список файлов версии с sha256 и размером;
  index/LATEST                  — номер текущей версии; пишется последним, поэтому не указывает на неполную.

Выкладка — локально по статическому ключу (`S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, подпись SigV4).
Стенд скачивает индекс при старте по IAM-токену своего сервисного аккаунта из метаданных Serverless Containers
(заголовок `X-YaCloud-SubjectToken`): статического ключа в контейнере нет.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

import httpx

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://storage.yandexcloud.net"
REGION = "ru-central1"
METADATA_TOKEN_URL = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"  # noqa: S105
# Только эти файлы индекса уходят в бакет и только их стенд согласится записать (имена из манифеста — не пути).
FILES = ("passport.json", "fragments.jsonl", "vectors.npy", "cache/embeddings.jsonl")
REQUIRED = ("passport.json", "fragments.jsonl")
VERSION_FILE = ".kb-version"
_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

Auth = Callable[[str, str, dict[str, str], str], dict[str, str]]  # (method, url, headers, sha256) → заголовки


class KbError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_url(endpoint: str, bucket: str, key: str) -> str:
    return f"{endpoint.rstrip('/')}/{bucket}/{quote(key, safe='/-_.~')}"


# ---------- авторизация ----------


def _canonical_query(query: str) -> str:
    """SigV4: параметры отсортированы, ключ и значение закодированы (RFC 3986). Нет параметров — пустая строка."""
    pairs = sorted(parse_qsl(query, keep_blank_values=True))
    return "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in pairs)


def sigv4_auth(key_id: str, secret: str, region: str = REGION, now: Callable[[], dt.datetime] | None = None) -> Auth:
    """Подпись AWS SigV4 для S3 API Object Storage (path-style; параметры запроса — канонически, для списка)."""

    def sign(method: str, url: str, headers: dict[str, str], payload_sha: str) -> dict[str, str]:
        t = (now or (lambda: dt.datetime.now(dt.UTC)))()
        amz_date, day = t.strftime("%Y%m%dT%H%M%SZ"), t.strftime("%Y%m%d")
        parts = urlsplit(url)
        signed = {k.lower(): v.strip() for k, v in headers.items()}
        signed.update({"host": parts.netloc, "x-amz-content-sha256": payload_sha, "x-amz-date": amz_date})
        names = sorted(signed)
        canonical = "\n".join(
            [
                method,
                parts.path or "/",
                _canonical_query(parts.query),
                "".join(f"{n}:{signed[n]}\n" for n in names),
                ";".join(names),
                payload_sha,
            ]
        )
        scope = f"{day}/{region}/s3/aws4_request"
        to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{_sha256(canonical.encode())}"
        k = f"AWS4{secret}".encode()
        for part in (day, region, "s3", "aws4_request"):
            k = hmac.new(k, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        out = {n: signed[n] for n in names if n != "host"}
        out["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"
        )
        return out

    return sign


def metadata_token(http: httpx.Client) -> str:
    """IAM-токен сервисного аккаунта контейнера из сервиса метаданных."""
    try:
        r = http.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=5)
        r.raise_for_status()
        token = r.json()["access_token"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        hint = "у контейнера есть сервисный аккаунт?"
        raise KbError(f"нет IAM-токена из метаданных ({type(exc).__name__}): {hint}") from None
    if not isinstance(token, str) or not token:
        raise KbError("метаданные вернули пустой IAM-токен")
    return token


def iam_auth(token: str) -> Auth:
    def sign(method: str, url: str, headers: dict[str, str], payload_sha: str) -> dict[str, str]:
        return {**headers, "X-YaCloud-SubjectToken": token}

    return sign


# ---------- чтение (стенд) ----------


class Bucket:
    def __init__(self, bucket: str, auth: Auth, http: httpx.Client, endpoint: str = DEFAULT_ENDPOINT) -> None:
        self.bucket, self.auth, self.http, self.endpoint = bucket, auth, http, endpoint

    def get(self, key: str) -> bytes:
        url = object_url(self.endpoint, self.bucket, key)
        r = self.http.get(url, headers=self.auth("GET", url, {}, _sha256(b"")), timeout=120)
        if r.status_code != 200:
            raise KbError(f"GET {key}: HTTP {r.status_code}")
        return r.content

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        url = object_url(self.endpoint, self.bucket, key)
        headers = self.auth("PUT", url, {"content-type": content_type}, _sha256(data))
        r = self.http.put(url, content=data, headers=headers, timeout=600)
        if r.status_code not in (200, 201):
            raise KbError(f"PUT {key}: HTTP {r.status_code}")


def fetch_index(bucket: Bucket, dest: Path) -> str:
    """Скачать index/LATEST → index/<версия>/ в dest. Файлы сверяются с манифестом; dest заменяется целиком
    только после успешной сверки. Уже скачанная та же версия не качается повторно. Возвращает версию."""
    version = bucket.get("index/LATEST").decode("utf-8").strip()
    if not _VERSION_RE.match(version):
        raise KbError("index/LATEST: недопустимый номер версии")
    marker = dest / VERSION_FILE
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == version:
        return version
    manifest = json.loads(bucket.get(f"index/{version}/MANIFEST.json"))
    files: dict[str, Any] = manifest.get("files", {})
    unknown = set(files) - set(FILES)
    if unknown:
        raise KbError(f"манифест {version}: недопустимые файлы {sorted(unknown)}")
    missing = set(REQUIRED) - set(files)
    if missing:
        raise KbError(f"манифест {version}: нет {sorted(missing)}")
    tmp = dest.parent / f".{dest.name}.tmp-{version}"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        for name, meta in files.items():
            data = bucket.get(f"index/{version}/{name}")
            if len(data) != int(meta["size"]) or _sha256(data) != meta["sha256"]:
                raise KbError(f"{name}: не совпал с манифестом {version}")
            (tmp / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp / name).write_bytes(data)
        (tmp / VERSION_FILE).write_text(version, encoding="utf-8")
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return version


def installed_version(dest: Path) -> str | None:
    marker = dest / VERSION_FILE
    return marker.read_text(encoding="utf-8").strip() if marker.is_file() else None


def _env_bucket(http: httpx.Client, *, allow_static: bool) -> Bucket:
    name = os.environ.get("S3_BUCKET", "").strip()
    if not name:
        raise KbError("S3_BUCKET не задан")
    endpoint = os.environ.get("S3_ENDPOINT", DEFAULT_ENDPOINT)
    key_id, secret = os.environ.get("S3_ACCESS_KEY_ID", ""), os.environ.get("S3_SECRET_ACCESS_KEY", "")
    if allow_static and key_id and secret:
        return Bucket(name, sigv4_auth(key_id, secret), http, endpoint)
    if not allow_static:
        if key_id or secret:
            log.warning("S3_ACCESS_KEY_ID/S3_SECRET_ACCESS_KEY в окружении стенда не используются: читаем по IAM")
        return Bucket(name, iam_auth(metadata_token(http)), http, endpoint)
    raise KbError("нужны S3_ACCESS_KEY_ID и S3_SECRET_ACCESS_KEY (статический ключ, только локально)")


LAST_ERROR: dict[str, str] = {}  # причина последней неудачной загрузки индекса — для /health


def ensure_index_from_env(http: httpx.Client | None = None) -> str | None:
    """При старте сервиса: если задан S3_BUCKET — скачать индекс в INDEX_DIR по IAM-токену из метаданных.
    Ошибка не роняет сервис: поиск останется пустым (STUB: search-until-#3), причина — в журнале и /health."""
    if not os.environ.get("S3_BUCKET", "").strip():
        return None
    from service.manuals.index import index_dir

    own = http is None
    client = http or httpx.Client()
    try:
        version = fetch_index(_env_bucket(client, allow_static=False), index_dir())
        log.info("индекс руководств %s скачан в %s", version, index_dir())
        LAST_ERROR.clear()
        return version
    except (KbError, httpx.HTTPError, OSError, ValueError) as exc:
        log.error("индекс руководств из бакета не скачан: %s", exc)
        LAST_ERROR["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return None
    finally:
        if own:
            client.close()


# ---------- выкладка (локально) ----------


def build_manifest(src: Path) -> dict[str, Any]:
    files = {}
    for name in FILES:
        p = src / name
        if p.is_file():
            data = p.read_bytes()
            files[name] = {"sha256": _sha256(data), "size": len(data)}
    missing = set(REQUIRED) - set(files)
    if missing:
        raise KbError(f"в {src} нет {sorted(missing)} — сначала make index")
    return {"files": files}


def publish_index(bucket: Bucket, src: Path, now: dt.datetime | None = None) -> str:
    """Выложить индекс новой версией; index/LATEST — последним. Возвращает версию."""
    manifest = build_manifest(src)
    t = now or dt.datetime.now(dt.UTC)
    version = f"{t:%Y%m%d-%H%M%S}-{manifest['files']['fragments.jsonl']['sha256'][:8]}"
    manifest["version"] = version
    for name in manifest["files"]:
        bucket.put(f"index/{version}/{name}", (src / name).read_bytes())
    body = json.dumps(manifest, ensure_ascii=False, indent=1).encode()
    bucket.put(f"index/{version}/MANIFEST.json", body, "application/json")
    bucket.put("index/LATEST", version.encode(), "text/plain")
    return version


def publish_manuals(bucket: Bucket, src: Path) -> list[str]:
    from service.manuals.catalog import DOCUMENTS

    done = []
    for doc in DOCUMENTS:
        path = src / doc.file
        if not path.is_file():
            raise KbError(f"нет PDF {doc.file} в {src}")
        bucket.put(f"manuals/{doc.file}", path.read_bytes(), "application/pdf")
        done.append(doc.file)
    return done


def main(argv: list[str] | None = None) -> int:
    import argparse

    from service.manuals.index import index_dir, manuals_dir

    p = argparse.ArgumentParser(prog="python -m service.kb_store", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pub = sub.add_parser("publish", help="выложить индекс (и PDF с --manuals) по статическому ключу")
    pub.add_argument("--index", type=Path)
    pub.add_argument("--manuals", action="store_true", help="выложить и PDF из MANUALS_DIR в manuals/")
    fe = sub.add_parser("fetch", help="скачать индекс index/LATEST по статическому ключу (проверка выкладки)")
    fe.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with httpx.Client() as http:
        bucket = _env_bucket(http, allow_static=True)
        if args.cmd == "publish":
            if args.manuals:
                print("PDF:", ", ".join(publish_manuals(bucket, manuals_dir())))
            print("индекс выложен, версия", publish_index(bucket, args.index or index_dir()))
        else:
            version = fetch_index(bucket, args.out)
            print("скачана версия", version, "→", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
