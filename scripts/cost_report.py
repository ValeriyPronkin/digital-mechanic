"""Себестоимость по участкам (issue #16): прогон сценариев на настоящей модели → CSV по шагам + reports/cost.md.

  make cost LABEL=baseline        # замер; LABEL — имя замера (до/после оптимизации)
  uv run --env-file .env python scripts/cost_report.py --label after-cache --repeat 2

Модель и ключ — из .env (LLM_PROVIDER), индекс руководств — .index/, заглушки ML и ТОиР — в процессе.
Каждый сценарий — новый разговор и пустой журнал. Качество ответа проверяется автоматически на том же прогоне:
оптимизация, после которой проверка упала, не принимается.

Файлы: reports/cost/<label>.csv (строка на шаг агента — для шаблона организаторов), reports/cost/<label>.json
(итоги), reports/cost.md — сводка по всем замерам, «до» — первый замер, «после» — последний.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "cost"
sys.path.insert(0, str(ROOT / "vendor" / "neurodvs_mock"))

from fastapi.testclient import TestClient  # noqa: E402
from mock_ml.app import app as mock_ml_app  # noqa: E402
from mock_toir.app import app as mock_toir_app  # noqa: E402

from service.agent import Agent, AgentReply  # noqa: E402
from service.clients import MLClient, ToirClient  # noqa: E402
from service.fleet import fleet  # noqa: E402
from service.llm import provider_from_env  # noqa: E402
from service.manual_search import default_searcher  # noqa: E402
from service.manuals.catalog import documents_for_engine  # noqa: E402
from service.store import Store, price_table  # noqa: E402

CUT_NOTE = "Часть цифр не нашёл"
Check = Callable[[AgentReply, str], str | None]  # (ответ, двигатель) → None или что не так


def grounded_own_engine(r: AgentReply, engine: str) -> str | None:
    if not r.grounded or not r.sources:
        return "нет ссылок на руководство"
    own = {d.designation for d in documents_for_engine(engine)}
    if any(s["manual"] not in own for s in r.sources):
        return "ссылка на чужое руководство"
    return None


def no_cut(r: AgentReply, engine: str) -> str | None:
    return "проверка вырезала цифры" if any(CUT_NOTE in n for n in r.notes) else None


def has_draft(r: AgentReply, engine: str) -> str | None:
    if r.draft is None:
        return "нет черновика заявки"
    body = r.draft["body"]
    return None if body["references"] and body["operations"] else "черновик без работ или ссылок"


def no_draft(r: AgentReply, engine: str) -> str | None:
    return "черновик заявки там, где его быть не может" if r.draft else None


def mentions(*words: str) -> Check:
    def check(r: AgentReply, engine: str) -> str | None:
        low = r.text.lower()
        return None if any(w in low for w in words) else f"в ответе нет «{' / '.join(words)}»"

    return check


@dataclass
class Turn:
    question: str
    checks: list[Check]


@dataclass
class Scenario:
    key: str
    title: str
    vehicle_id: str
    session_id: str
    turns: list[Turn]
    voice: bool = False  # плюс распознавание вопроса и синтез ответа (оценка по тарифу)


SCENARIOS = [
    Scenario(
        "С1",
        "Отклонение → объяснение → заявка (F02, ЯМЗ-536)",
        "A464EP47",
        "S-0096",
        [
            Turn("Что с двигателем и что делать?", [grounded_own_engine, no_cut, no_draft]),
            Turn("Оформи заявку", [has_draft]),
        ],
    ),
    Scenario(
        "С2",
        "Норма: вопрос механика (ЯМЗ-536)",
        "",
        "",
        [Turn("Что с двигателем?", [no_draft, mentions("норм")])],
    ),
    Scenario(
        "С3",
        "Сбой проверки + инъекция в описании (ЗМЗ)",
        "H142OX78",
        "S-0113",
        [Turn("Что с двигателем? Оформи заявку", [no_draft, mentions("повтор")])],
    ),
    Scenario(
        "Р1",
        "Вопрос по руководству: тепловой зазор (F01, ЯМЗ-536)",
        "O658MX98",
        "S-0061",
        [Turn("Какой тепловой зазор клапанов нужен?", [grounded_own_engine, no_cut, mentions("0,30", "0,3")])],
    ),
    Scenario(
        "Н1",
        "Несовместимый код: бензин на дизеле (ЯМЗ-536)",
        "M260EH47",
        "S-0079",
        [Turn("Оформи заявку", [no_draft, mentions("повтор")])],
    ),
    Scenario(
        "Г1",
        "Голосовой вопрос (как С1, вопрос 1; распознавание и синтез — оценка, голос — #14)",
        "A464EP47",
        "S-0096",
        [Turn("Что с двигателем и что делать?", [grounded_own_engine, no_cut])],
        voice=True,
    ),
]


def _normal_yamz() -> tuple[str, str]:
    for v in fleet().vehicles:
        if v.engine_model == "ЯМЗ-536":
            for s in v.sessions:
                if s.status == "normal" and s.signal_quality == "good" and (s.anomaly_score or 0) < 0.3:
                    return v.vehicle_id, s.session_id
    raise SystemExit("нет нормальной проверки ЯМЗ-536 в данных")


@dataclass
class Result:
    scenario: str
    title: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    rub_llm: float = 0.0
    rub_other: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0


def voice_rub(answer: str) -> tuple[float, str]:
    other = price_table()["other"]
    stt = other["stt_sync"]["value"] or 0.0  # вопрос до 15 с — один отрезок
    tts = other["tts"]["value"]
    if tts is None:
        return stt, "распознавание 15 с; синтез — тариф не найден, не учтён"
    return stt + tts * len(answer) / 1_000_000, f"распознавание 15 с + синтез {len(answer)} символов"


def run(sc: Scenario, provider: Any, searcher: Any) -> Result:
    store = Store(":memory:")
    ag = Agent(
        provider,
        MLClient(http=TestClient(mock_ml_app)),
        ToirClient(http=TestClient(mock_toir_app)),
        searcher,
        store,
        fleet(),
    )
    vid, sid = (sc.vehicle_id, sc.session_id) if sc.vehicle_id else _normal_yamz()
    conv = ag.start(vid, sid)
    res = Result(sc.key, sc.title)
    for n, turn in enumerate(sc.turns, 1):
        reply = ag.ask(conv, turn.question)
        for chk in turn.checks:
            bad = chk(reply, conv.vehicle.engine_model)
            if bad:
                res.problems.append(f"вопрос {n}: {bad}")
        for st in reply.trace["steps"]:
            row = {
                "scenario": sc.key,
                "question": n,
                "step": st["step"],
                "kind": "модель" if st["kind"] == "llm" else "инструмент",
                "name": st["name"],
                "tokens_in": st.get("tokens_in", 0),
                "tokens_cached": st.get("tokens_cached", 0),
                "tokens_out": st.get("tokens_out", 0),
                "rub": st.get("cost_rub", 0.0),
                "ms": st["ms"],
            }
            res.rows.append(row)
            res.tokens_in += row["tokens_in"]
            res.tokens_out += row["tokens_out"]
            res.tokens_cached += row["tokens_cached"]
            res.rub_llm += row["rub"]
        if sc.voice:
            rub, what = voice_rub(reply.text)
            res.rows.append(
                {"scenario": sc.key, "question": n, "step": 0, "kind": "речь", "name": what, "tokens_in": 0,
                 "tokens_cached": 0, "tokens_out": 0, "rub": round(rub, 4), "ms": 0}
            )  # fmt: skip
            res.rub_other += rub
    # эмбеддинг запроса: ~ длина вопроса / 3 токена на каждый search_manual — копейки, считаем по тарифу
    emb_price = price_table()["other"]["embedding"]["value"]
    searches = sum(1 for r in res.rows if r["name"] == "search_manual")
    res.rub_other += searches * 20 * emb_price / 1000
    return res


def write(label: str, results: list[Result], repeat: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / f"{label}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].rows[0].keys()))
        w.writeheader()
        for r in results:
            w.writerows(r.rows)
    summary = {
        "label": label,
        "at": f"{datetime.now():%Y-%m-%d %H:%M}",
        "repeat": repeat,
        "scenarios": {
            r.scenario: {
                "title": r.title,
                "rub": round((r.rub_llm + r.rub_other) / repeat, 4),
                "rub_llm": round(r.rub_llm / repeat, 4),
                "llm_calls": round(sum(1 for x in r.rows if x["kind"] == "модель") / repeat, 1),
                "tokens_in": r.tokens_in // repeat,
                "tokens_cached": r.tokens_cached // repeat,
                "tokens_out": r.tokens_out // repeat,
                "problems": r.problems,
            }
            for r in results
        },
    }
    (OUT_DIR / f"{label}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    render_md()


def render_md() -> None:
    runs = sorted((json.loads(p.read_text(encoding="utf-8")) for p in OUT_DIR.glob("*.json")), key=lambda d: d["at"])
    if not runs:
        return
    first, last = runs[0], runs[-1]
    prices = price_table()
    lines = [
        "# Себестоимость по участкам (issue #16)",
        "",
        "Замеры: " + ", ".join(f"`{r['label']}` ({r['at']})" for r in runs) + f". «До» — `{first['label']}`, "
        f"«после» — `{last['label']}`. Скрипт: `make cost LABEL=…`; строки по шагам — `reports/cost/<замер>.csv`.",
        "",
        "Карточка проверки (норма / отклонение / сбой) строится кодом: **0 токенов**, 0 ₽ на модель.",
        "",
        "| Сценарий | Вызовов модели | Токены вход (из кэша) / выход | ₽ до | ₽ после | Качество |",
        "|---|---|---|---|---|---|",
    ]
    for key, s in last["scenarios"].items():
        before = first["scenarios"].get(key, {})
        q = "✅" if not s["problems"] else "❌ " + "; ".join(s["problems"])
        lines.append(
            f"| {key} — {s['title']} | {s['llm_calls']} | {s['tokens_in']} ({s['tokens_cached']}) / {s['tokens_out']}"
            f" | {before.get('rub', '—')} | {s['rub']} | {q} |"
        )
    lines += ["", "## Все замеры", "", "| Замер | " + " | ".join(last["scenarios"]) + " |",
              "|---|" + "---|" * len(last["scenarios"])]  # fmt: skip
    for r in runs:
        lines.append(
            f"| `{r['label']}` | "
            + " | ".join(
                f"{r['scenarios'][k]['rub']} ₽{'' if not r['scenarios'][k]['problems'] else ' ❌'}"
                if k in r["scenarios"]
                else "—"
                for k in last["scenarios"]
            )
            + " |"
        )
    lines += ["", "## Тарифы", "", "| Участок | Цена | Источник | Уверенность |", "|---|---|---|---|"]
    for name, row in prices["llm"].items():
        val = row.get("rub") or {k: f"${v}" for k, v in row.get("usd", {}).items()}
        lines.append(f"| модель {name} | {val} ({row['unit']}) | {row['source']} | {row['confidence']} |")
    for name, row in prices["other"].items():
        v = "не найдено" if row["value"] is None else f"{row['value']} {row['unit']}"
        lines.append(f"| {name} | {v} | {row['source']} | {row['confidence']} |")
    u = prices["usd_rub"]
    lines += [f"| курс | {u['value']} ₽/$ | {u['source']} | {u['confidence']} |", ""]
    (ROOT / "reports" / "cost.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=f"{datetime.now():%Y%m%d-%H%M}")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only", help="сценарии через запятую, например С1,Г1")
    args = ap.parse_args()
    provider, searcher = provider_from_env(), default_searcher()
    chosen = [s for s in SCENARIOS if not args.only or s.key in args.only.split(",")]
    results = []
    for sc in chosen:
        merged = Result(sc.key, sc.title)
        for _ in range(args.repeat):
            r = run(sc, provider, searcher)
            merged.rows += r.rows
            merged.problems += r.problems
            merged.rub_llm += r.rub_llm
            merged.rub_other += r.rub_other
            merged.tokens_in += r.tokens_in
            merged.tokens_out += r.tokens_out
            merged.tokens_cached += r.tokens_cached
        results.append(merged)
        tag = "ok" if not merged.problems else "; ".join(merged.problems)
        print(f"{sc.key}: {(merged.rub_llm + merged.rub_other) / args.repeat:.4f} ₽ — {tag}")
    write(args.label, results, args.repeat)
    print(f"reports/cost/{args.label}.csv, reports/cost.md")
    return 0 if all(not r.problems for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
