"""Открытая половина вопросов приёмщика (issue #28): прогон на настоящей модели и индексе, оценка по эталонам.

  make eval-open LABEL=baseline        # вопросы — EVAL_OPEN (по умолчанию ~/dm-eval/questions_open.jsonl)

Вопросы и эталоны в репозиторий не кладём: в отчёт идут только номера вопросов, итоги и найденные страницы.
Засчитано, если:
  - вопрос с отказом (expect.refuse) — нет ни черновика, ни цифр из чужого руководства, в ответе «нет в руководстве»
    или «дефектовка»;
  - иначе — в источниках ответа есть эталонная страница (основная или из also) **и** все эталонные значения есть в
    тексте ответа (без учёта регистра, пробелов, вида тире и многоточия).
Отдельно считаются: страница найдена, значения в ответе, чужой двигатель (источник не из руководств двигателя ТС).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "neurodvs_mock"))

from fastapi.testclient import TestClient  # noqa: E402
from mock_ml.app import app as mock_ml_app  # noqa: E402
from mock_toir.app import app as mock_toir_app  # noqa: E402

from service.agent import Agent  # noqa: E402
from service.clients import MLClient, ToirClient  # noqa: E402
from service.fleet import fleet  # noqa: E402
from service.llm import provider_from_env  # noqa: E402
from service.manual_search import default_searcher  # noqa: E402
from service.manuals.catalog import DOCUMENTS, documents_for_engine  # noqa: E402
from service.store import Store  # noqa: E402

DEFAULT = "~/dm-eval/questions_open.jsonl"
OUT = ROOT / "reports" / "eval"
REFUSE_WORDS = ("нет в руководстве", "не нашёл", "не нашел", "в руководстве не", "дефектовк", "нет данных",
                "не указан", "не приводится", "отсутству")  # fmt: skip


def norm(text: str) -> str:
    """Регистр, пробелы, ё и разделитель диапазона не важны: «0,20…0,30» = «0,20–0,30» = «0,20 - 0,30»."""
    t = text.lower().replace("ё", "е").replace(" ", " ")
    t = re.sub(r"\s+", "", t)
    return re.sub(r"(?<=\d)(?:\.\.\.|…|[–—−-]|до)(?=\d)", "-", t)


def doc_of(manual: str | None) -> str | None:
    """«… (ЯМЗ_236_руководство по эксплуатации.pdf)» → doc_id каталога."""
    if not manual:
        return None
    m = re.search(r"\(([^()]+\.pdf)\)", manual)
    name = m.group(1) if m else manual
    return next((d.doc_id for d in DOCUMENTS if d.file == name), None)


def expected_pages(e: dict[str, Any]) -> set[tuple[str | None, int]]:
    pages = {(doc_of(e.get("manual")), p) for p in e.get("pages") or []}
    for a in e.get("also") or []:
        pages |= {(doc_of(a.get("manual")), p) for p in a.get("pages") or []}
    return pages


def score(q: dict[str, Any], reply: Any, engine_model: str) -> dict[str, Any]:
    e = q["expect"]
    own = {d.designation for d in documents_for_engine(engine_model)}
    designation_to_id = {d.designation: d.doc_id for d in DOCUMENTS}
    src = {(designation_to_id.get(s["manual"]), int(s["pdf_page"])) for s in reply.sources}
    foreign = any(s["manual"] not in own for s in reply.sources)
    text = norm(reply.text)
    values = [v for v in e.get("values") or []]
    values_ok = all(norm(v) in text for v in values)
    if e.get("refuse"):
        refused = any(norm(w) in text for w in REFUSE_WORDS)
        ok = refused and not foreign and reply.draft is None
        return {"ok": ok, "page": None, "values": None, "foreign": foreign, "refused": refused}
    page_ok = bool(src & expected_pages(e))
    return {"ok": page_ok and values_ok and not foreign, "page": page_ok, "values": values_ok, "foreign": foreign,
            "missing": [v for v in values if norm(v) not in text],
            "found_pages": sorted(p for _, p in src)}  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=f"{datetime.now():%Y%m%d-%H%M}")
    ap.add_argument("--only", help="номера через запятую, например Q02,Q20")
    ap.add_argument("--show", action="store_true", help="печатать ответы (для разбора; в отчёт не идут)")
    args = ap.parse_args()
    path = Path(os.environ.get("EVAL_OPEN", DEFAULT)).expanduser()
    questions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only:
        questions = [q for q in questions if q["id"] in args.only.split(",")]
    provider, searcher = provider_from_env(), default_searcher()
    results = []
    for q in questions:
        ag = Agent(provider, MLClient(http=TestClient(mock_ml_app)), ToirClient(http=TestClient(mock_toir_app)),
                   searcher, Store(":memory:"), fleet())  # fmt: skip
        conv = ag.start(q["vehicle_id"], q["session_id"])
        try:
            reply = ag.ask(conv, q["question"])
        except Exception as exc:  # сбой одного вопроса — провал вопроса, не прогона
            results.append({"id": q["id"], "type": q["type"], "ok": False, "error": type(exc).__name__, "rub": 0})
            print(f"{q['id']}: ОШИБКА {exc}")
            continue
        s = score(q, reply, conv.vehicle.engine_model)
        ANSWERS.mkdir(parents=True, exist_ok=True)
        with (ANSWERS / f"{args.label}.jsonl").open("a", encoding="utf-8") as f:
            rec = {"id": q["id"], "text": reply.text, "sources": reply.sources}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        s.update({"id": q["id"], "type": q["type"], "tags": q.get("tags", []), "rub": reply.trace["cost_rub"],
                  "calls": sum(1 for x in reply.trace["steps"] if x["kind"] == "llm")})  # fmt: skip
        results.append(s)
        mark = "✅" if s["ok"] else "❌"
        extra = "" if s["ok"] else f" стр.{s.get('found_pages')} нет:{s.get('missing')} отказ:{s.get('refused')}"
        print(f"{q['id']} {mark} {s['rub']:.3f} ₽{extra}")
        if args.show:
            print("   " + reply.text.replace("\n", "\n   ")[:1500])
    write(args.label, results)
    return 0


ANSWERS = ROOT / ".state" / "eval"  # ответы для разбора — вне git


def write(label: str, results: list[dict[str, Any]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    n = len(results)
    answerable = [r for r in results if r.get("page") is not None]
    summary = {
        "label": label,
        "at": f"{datetime.now():%Y-%m-%d %H:%M}",
        "passed": sum(1 for r in results if r["ok"]),
        "total": n,
        "page_found": sum(1 for r in answerable if r["page"]),
        "values_in_answer": sum(1 for r in answerable if r["values"]),
        "answerable": len(answerable),
        "foreign": sum(1 for r in results if r.get("foreign")),
        "rub_per_question": round(sum(r.get("rub", 0) for r in results) / max(n, 1), 4),
        "results": results,
    }
    for r in summary["results"]:  # эталонные значения в репозиторий не кладём
        r.pop("missing", None)
    (OUT / f"{label}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    runs = sorted((json.loads(p.read_text(encoding="utf-8")) for p in OUT.glob("*.json")), key=lambda d: d["at"])
    lines = [
        "# Открытая половина вопросов приёмщика (issue #28)",
        "",
        "Вопросы и эталоны — вне репозитория (`EVAL_OPEN`); здесь только итоги. Скрипт: `make eval-open LABEL=…`.",
        "",
        "| Замер | Засчитано | Страница найдена | Значения в ответе | Чужой двигатель | ₽ на вопрос |",
        "|---|---|---|---|---|---|",
    ]
    for r in runs:
        lines.append(
            f"| `{r['label']}` ({r['at']}) | {r['passed']}/{r['total']} | {r['page_found']}/{r['answerable']} | "
            f"{r['values_in_answer']}/{r['answerable']} | {r['foreign']} | {r['rub_per_question']} |"
        )
    last = runs[-1]
    lines += ["", f"## По вопросам (`{last['label']}`)", "", "| № | Тип | Итог | Страница | Значения | ₽ |",
              "|---|---|---|---|---|---|"]  # fmt: skip
    for r in last["results"]:

        def yn(v: Any) -> str:
            return "—" if v is None else ("да" if v else "нет")

        lines.append(f"| {r['id']} | {r['type']} | {'✅' if r['ok'] else '❌'} | {yn(r.get('page'))} | "
                     f"{yn(r.get('values'))} | {r.get('rub', 0)} |")  # fmt: skip
    (ROOT / "reports" / "eval-open.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{last['passed']}/{last['total']} · страница {last['page_found']}/{last['answerable']} · значения "
          f"{last['values_in_answer']}/{last['answerable']} · чужих {last['foreign']} · "
          f"{last['rub_per_question']} ₽")  # fmt: skip


if __name__ == "__main__":
    sys.exit(main())
