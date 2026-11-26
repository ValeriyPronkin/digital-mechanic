"""CLI индекса руководств.

  python -m service.manuals build              — собрать индекс (PDF из MANUALS_DIR → INDEX_DIR)
  python -m service.manuals search "вопрос" --engine ЯМЗ-236М2   — топ-5: документ, страница, раздел, цитата
  python -m service.manuals passport           — паспорт PDF из собранного индекса
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .index import build_index, index_dir
from .search import ManualIndex, UnknownEngineError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m service.manuals")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="собрать индекс")
    b.add_argument("--src", type=Path, help="каталог PDF (по умолчанию MANUALS_DIR)")
    b.add_argument("--out", type=Path, help="каталог индекса (по умолчанию INDEX_DIR или .index)")
    b.add_argument("--no-yandex", action="store_true", help="без OCR и эмбеддингов")
    s = sub.add_parser("search", help="поиск по руководствам двигателя")
    s.add_argument("query")
    s.add_argument("--engine", required=True, help="модель двигателя из карточки ТС, например ЯМЗ-236М2")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--index", type=Path)
    s.add_argument("--lexical", action="store_true", help="только по словам")
    s.add_argument("--json", action="store_true")
    ps = sub.add_parser("passport", help="паспорт PDF")
    ps.add_argument("--index", type=Path)
    args = p.parse_args(argv)

    if args.cmd == "build":
        build_index(args.src, args.out, use_yandex=not args.no_yandex)
        return 0
    if args.cmd == "passport":
        path = (args.index or index_dir()) / "passport.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for d in data["documents"]:
            print(
                f"{d['doc_id']}: {d['pages']} стр., без текста {len(d['low_text_pages'])} "
                f"(OCR {len(d['ocr_pages'])}), печатный−PDF {d['printed_minus_pdf']}, "
                f"разделов {len(d['toc'])}, таблиц {d['tables']}, строк неисправностей {d['fault_rows']}"
            )
        return 0

    index = ManualIndex.load(args.index, semantic=not args.lexical)
    try:
        hits = index.search(args.query, args.engine, k=args.k)
    except UnknownEngineError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.json:
        out = [
            {
                "doc_id": h.fragment.doc_id,
                "designation": h.fragment.designation,
                "page": h.fragment.page,
                "section": h.fragment.section,
                "kind": h.fragment.kind,
                "source": h.fragment.source,
                "quote": h.quote,
                "score": round(h.score, 5),
            }
            for h in hits
        ]
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    mode = "слова + смысл" if index.semantic else "только слова"
    print(f"«{args.query}» · {args.engine} · {mode}")
    for n, h in enumerate(hits, 1):
        f = h.fragment
        print(f"\n{n}. {f.designation} — стр. {f.page} (PDF) · {f.kind} · {f.source}")
        if f.section:
            print(f"   Раздел: {f.section}")
        print(f"   «{h.quote}»")
    if not hits:
        print("Ничего не найдено в руководствах этого двигателя.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
