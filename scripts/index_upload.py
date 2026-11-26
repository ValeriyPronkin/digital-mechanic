"""Выкладка PDF руководств и собранного индекса в бакет Object Storage (D-9).

Раскладка:
  manuals/<файл>          — PDF из MANUALS_DIR (повторно не грузятся, если размер совпал);
  index/<версия>/...      — fragments.jsonl, vectors.npy, passport.json, cache/embeddings.jsonl, cache/ocr/*,
                            manifest.json (sha256 и размер каждого файла);
  index/LATEST            — номер версии; пишется последним, после проверки всех файлов версии.

Версия — дата сборки и первые 10 знаков sha256 содержимого индекса: тот же индекс → та же версия,
повторная выкладка ничего не перезаписывает. Кэш извлечения (`cache/extract`) не грузится.

  make index-upload            (нужны S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY)
  uv run --env-file .env python scripts/index_upload.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from service.manuals.catalog import DOCUMENTS
from service.manuals.index import index_dir, manuals_dir

INDEX_FILES = ("fragments.jsonl", "vectors.npy", "passport.json", "cache/embeddings.jsonl")
CONTENT_TYPES = {".jsonl": "application/x-ndjson", ".json": "application/json", ".pdf": "application/pdf"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def index_files(root: Path) -> list[str]:
    """Файлы версии индекса (пути относительно INDEX_DIR). Обязательные — fragments и passport."""
    for required in ("fragments.jsonl", "passport.json"):
        if not (root / required).is_file():
            raise FileNotFoundError(f"индекс не собран: нет {root / required} (make index)")
    files = [f for f in INDEX_FILES if (root / f).is_file()]
    files += sorted(str(p.relative_to(root)) for p in (root / "cache" / "ocr").glob("*.txt"))
    return files


def build_manifest(root: Path, files: list[str], built_at: datetime) -> dict[str, Any]:
    entries = {f: {"sha256": sha256(root / f), "size": (root / f).stat().st_size} for f in files}
    content = hashlib.sha256(
        "".join(f"{f}:{entries[f]['sha256']}\n" for f in sorted(entries)).encode("utf-8")
    ).hexdigest()
    passport = json.loads((root / "passport.json").read_text(encoding="utf-8"))
    return {
        "version": f"{built_at:%Y%m%d}-{content[:10]}",
        "built_at": built_at.isoformat(timespec="seconds"),
        "meta": passport.get("meta", {}),
        "files": entries,
    }


def s3_client() -> Any:
    import boto3

    missing = [
        k for k in ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY") if not os.environ.get(k)
    ]
    if missing:
        raise SystemExit(f"не заданы переменные: {', '.join(missing)}")
    from botocore.config import Config

    return boto3.client(
        "s3",
        config=Config(retries={"max_attempts": 10, "mode": "standard"}, connect_timeout=20, read_timeout=120),
        endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("S3_REGION", "ru-central1"),
    )


def remote_size(s3: Any, bucket: str, key: str) -> int | None:
    from botocore.exceptions import ClientError

    try:
        return int(s3.head_object(Bucket=bucket, Key=key)["ContentLength"])
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def abort_incomplete(s3: Any, bucket: str, key: str) -> None:
    """Брошенная многочастная загрузка (обрыв сети, сон ноутбука) занимает место — отменяем."""
    resp = s3.list_multipart_uploads(Bucket=bucket, Prefix=key)
    for u in resp.get("Uploads", []):
        if u["Key"] == key:
            s3.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=u["UploadId"])


def upload(s3: Any, bucket: str, key: str, path: Path, dry: bool, attempts: int = 4) -> str:
    """Загрузить, если в бакете нет файла того же размера. Сбой сети — повтор файла целиком.

    Проверка TLS не ослабляется: при ошибке сертификата повторяем, а не отключаем verify.
    """
    from boto3.s3.transfer import TransferConfig
    from botocore.exceptions import BotoCoreError, ClientError

    size = path.stat().st_size
    if remote_size(s3, bucket, key) == size:
        return "есть"
    if dry:
        return "загрузил бы"
    extra = {"ContentType": CONTENT_TYPES.get(path.suffix, "application/octet-stream")}
    cfg = TransferConfig(multipart_threshold=64 << 20, multipart_chunksize=32 << 20, max_concurrency=2)
    for attempt in range(1, attempts + 1):
        try:
            s3.upload_file(str(path), bucket, key, ExtraArgs=extra, Config=cfg)
            return "загружен" if attempt == 1 else f"загружен с {attempt}-й попытки"
        except (BotoCoreError, ClientError, OSError) as e:
            abort_incomplete(s3, bucket, key)
            if attempt == attempts:
                raise
            print(f"  {key}: сбой ({type(e).__name__}), повтор {attempt + 1}/{attempts}", file=sys.stderr)
            time.sleep(5 * attempt)
    raise RuntimeError("unreachable")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="показать, что будет загружено, ничего не меняя")
    ap.add_argument("--skip-pdf", action="store_true", help="не трогать manuals/")
    args = ap.parse_args()

    root, src = index_dir(), manuals_dir()
    files = index_files(root)
    built = datetime.fromtimestamp((root / "fragments.jsonl").stat().st_mtime, tz=UTC)
    manifest = build_manifest(root, files, built)
    version = manifest["version"]
    s3 = s3_client()
    bucket = os.environ["S3_BUCKET"]

    if not args.skip_pdf:
        for doc in DOCUMENTS:
            pdf = src / doc.file
            if not pdf.is_file():
                raise SystemExit(f"нет PDF: {pdf}")
            print(f"manuals/{doc.file}: {upload(s3, bucket, f'manuals/{doc.file}', pdf, args.dry_run)}")

    prefix = f"index/{version}"
    for f in files:
        state = upload(s3, bucket, f"{prefix}/{f}", root / f, args.dry_run)
        if not f.startswith("cache/ocr/"):
            print(f"{prefix}/{f}: {state}")
    print(f"{prefix}/cache/ocr/: {sum(1 for f in files if f.startswith('cache/ocr/'))} файлов")

    if args.dry_run:
        print(f"--dry-run: версия {version}, LATEST не меняется")
        return 0

    # Проверка до переключения LATEST: каждый файл версии на месте и нужного размера
    bad = [f for f in files if remote_size(s3, bucket, f"{prefix}/{f}") != manifest["files"][f]["size"]]
    if bad:
        print(f"не сошлись размеры, LATEST не меняю: {bad}", file=sys.stderr)
        return 1
    body = json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=f"{prefix}/manifest.json", Body=body, ContentType="application/json")
    s3.put_object(Bucket=bucket, Key="index/LATEST", Body=f"{version}\n".encode(), ContentType="text/plain")
    print(f"index/LATEST → {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
