"""Картинки страниц руководств для ссылок «стр. N» (задача Валерия, 26.11): каждая страница PDF → WebP.

  pages/<doc_id>/<pdf_page>.webp  — страница PDF с 1, как в индексе; ≈120 dpi, ширина ≤ 1400 px, WebP качество 70
  pages/manifest.json             — doc_id → число страниц и размеры каждой страницы

Шаг 1 — отрисовка локально в .state/pages (по одному PDF, без параллели; готовые файлы пропускаются).
Шаг 2 — только с --upload: загрузка в бакет S3_BUCKET по статическому ключу из .env, в префикс pages/ (index/ и
manuals/ не трогаем); ключи, которые уже есть в бакете, пропускаются.

  uv run --env-file .env python scripts/pages_publish.py [--doc yamz-236-re]            # отрисовать
  uv run --env-file .env python scripts/pages_publish.py --upload [--doc …]             # отрисовать и загрузить
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pypdfium2 as pdfium
from PIL import Image

from service import kb_store
from service.manuals.catalog import DOCUMENTS

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stand_logs import list_keys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".state" / "pages"
PREFIX = "pages"
DPI = 120
MAX_WIDTH = 1400
QUALITY = 70


def render_doc(doc_id: str, pdf_path: Path) -> list[list[int]]:
    """Отрисовать все страницы одного PDF (пропуская готовые). → размеры [ширина, высота] по страницам."""
    out_dir = OUT / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    sizes: list[list[int]] = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(len(pdf)):
            path = out_dir / f"{i + 1}.webp"
            if path.exists():
                with Image.open(path) as im:
                    sizes.append([im.width, im.height])
                continue
            page = pdf[i]
            img = page.render(scale=DPI / 72).to_pil()
            page.close()
            if img.width > MAX_WIDTH:
                img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "WEBP", quality=QUALITY, method=4)
            path.write_bytes(buf.getvalue())
            sizes.append([img.width, img.height])
    finally:
        pdf.close()
    return sizes


def bucket() -> kb_store.Bucket:
    auth = kb_store.sigv4_auth(os.environ["S3_ACCESS_KEY_ID"], os.environ["S3_SECRET_ACCESS_KEY"])
    endpoint = os.environ.get("S3_ENDPOINT", kb_store.DEFAULT_ENDPOINT)
    return kb_store.Bucket(os.environ["S3_BUCKET"], auth, httpx.Client(timeout=60), endpoint)


def upload_doc(b: kb_store.Bucket, doc_id: str) -> tuple[int, int]:
    """Загрузить страницы одного документа, которых ещё нет в бакете. → (загружено, пропущено)."""
    have = set(list_keys(b, f"{PREFIX}/{doc_id}/"))
    sent = skipped = 0
    for path in sorted((OUT / doc_id).glob("*.webp"), key=lambda p: int(p.stem)):
        key = f"{PREFIX}/{doc_id}/{path.name}"
        if key in have:
            skipped += 1
            continue
        b.put(key, path.read_bytes(), "image/webp")
        sent += 1
    return sent, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", help="один документ (doc_id), иначе все по очереди")
    ap.add_argument("--upload", action="store_true", help="загрузить в бакет (префикс pages/)")
    args = ap.parse_args()
    manuals = Path(os.environ.get("MANUALS_DIR", ROOT / "manuals")).expanduser()
    docs = [d for d in DOCUMENTS if not args.doc or d.doc_id == args.doc]
    if not docs:
        print(f"нет документа {args.doc}", file=sys.stderr)
        return 1
    manifest_path = OUT / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    b = bucket() if args.upload else None
    total_pages = total_bytes = 0
    for d in docs:
        sizes = render_doc(d.doc_id, manuals / d.file)
        size = sum(p.stat().st_size for p in (OUT / d.doc_id).glob("*.webp"))
        manifest[d.doc_id] = {"pages": len(sizes), "dpi": DPI, "sizes": sizes}
        total_pages += len(sizes)
        total_bytes += size
        line = f"{d.doc_id}: {len(sizes)} стр., {size / 2**20:.1f} МБ"
        if b is not None:
            sent, skipped = upload_doc(b, d.doc_id)
            line += f"; в бакет загружено {sent}, уже было {skipped}"
        print(line, flush=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")
    if b is not None:
        b.put(f"{PREFIX}/manifest.json", manifest_path.read_bytes(), "application/json")
    print(f"всего: {total_pages} стр., {total_bytes / 2**20:.1f} МБ; локально {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
