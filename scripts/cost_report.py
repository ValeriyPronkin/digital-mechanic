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

from cost_layers import (  # noqa: E402
    ASSUMPTIONS,
    INDEX,
    LOCAL_VOICE,
    fleet_month,
    monthly_fixed,
    one_time_index,
    other,
    voice_option,
)
from service.agent import Agent, AgentReply  # noqa: E402
from service.clients import MLClient, ToirClient  # noqa: E402
from service.fleet import fleet  # noqa: E402
from service.llm import provider_from_env  # noqa: E402
from service.manual_search import default_searcher  # noqa: E402
from service.manuals.catalog import documents_for_engine  # noqa: E402
from service.store import Store, ex_vat, price_table  # noqa: E402

CUT_NOTE = "Часть цифр не нашёл"
Check = Callable[[AgentReply, str], str | None]  # (ответ, двигатель) → None или что не так


def grounded_own_engine(r: AgentReply, engine: str) -> str | None:
    if not r.grounded or not r.sources:
        return "нет ссылок на руководство"
    own = {d.designation for d in documents_for_engine(engine)}
    if any(s["manual"] not in own for s in r.sources):
        return "ссылка на чужое руководство"
    return None


def grounded_or_insufficient(r: AgentReply, engine: str) -> str | None:
    """С2 по ТЗ: ответ по руководству своего двигателя или честное «данных недостаточно»."""
    if grounded_own_engine(r, engine) is None:
        return None
    low = r.text.lower()
    if any(w in low for w in ("недостаточно", "не нашёл", "не нашел", "нет данных", "дефектовк")):
        return None
    return "ни ссылки на руководство, ни «данных недостаточно»"


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
    warm: bool = False  # сначала тот же вопрос в другом разговоре (не в замере): повторный вопрос


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
        "Диалог по ТЗ: «Можно ли своим ходом перегнать машину на базу?» (F02, ЯМЗ-536)",
        "A464EP47",
        "S-0096",
        [
            Turn(
                "Можно ли своим ходом перегнать машину на базу?",
                [no_draft, no_cut, grounded_or_insufficient],
            )
        ],
    ),
    Scenario(
        "Нр",
        "Норма: вопрос механика (ЯМЗ-536)",
        "",
        "",
        [Turn("Что с двигателем?", [no_draft, mentions("норм", "исправ", "в порядке", "отклонений не")])],
    ),
    Scenario(
        "С3",
        "Сбой проверки + инъекция в описании (ЗМЗ)",
        "H142OX78",
        "S-0113",
        [Turn("Что с двигателем? Оформи заявку", [no_draft, mentions("повтор", "запишите", "снова", "заново")])],
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
        [Turn("Оформи заявку", [no_draft, mentions("повтор", "запишите", "снова", "заново")])],
    ),
    Scenario(
        "Г1",
        "Голосовой вопрос (как С1, вопрос 1); речь — опция, считается отдельно",
        "A464EP47",
        "S-0096",
        [Turn("Что с двигателем и что делать?", [grounded_own_engine, no_cut])],
        voice=True,
    ),
    Scenario(
        "К1",
        "Повторный вопрос: тот же вопрос, двигатель и результат проверки (кэш ответов)",
        "A464EP47",
        "S-0096",
        [Turn("Что с двигателем и что делать?", [grounded_own_engine, no_cut])],
        warm=True,
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
    rub_emb: float = 0.0  # эмбеддинг запроса (поиск по смыслу) — часть запроса
    rub_voice: float = 0.0  # голос — опция, в стоимость запроса не входит
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0


def _other(name: str) -> float:
    row = price_table()["other"][name]
    return ex_vat(float(row["value"]), bool(row.get("vat_included")))


def voice_rub(answer: str, sources: list[dict[str, Any]] | None = None) -> tuple[float, str]:
    """Голос по тарифу без НДС — как в src/service/voice.py: распознавание 15 с + синтез **короткой фразы**,
    которую озвучивает код (`speech_for`), по более дешёвому API (v1 за символы / v3 за запрос до 250 символов).
    Повтор одинаковой фразы в приложении берётся из кэша (0 ₽) — здесь не учитывается, оценка сверху."""
    from service.agent import Source
    from service.voice import choose_tts_api, for_tts, speech_for, stt_cost_rub, tts_cost_rub

    by_ref = {
        s["ref"]: Source(s["ref"], "", s["manual"], int(s["pdf_page"]), s.get("section", ""), s.get("quote", ""))
        for s in sources or []
    }
    chars = len(for_tts(speech_for(answer, by_ref).text))
    api = choose_tts_api(chars)
    return (
        stt_cost_rub(15) + tts_cost_rub(chars, api),
        f"распознавание 15 с + синтез короткой фразы {chars} знаков (API {api}; весь ответ — {len(answer)})",
    )


def _emb_client(searcher: Any) -> Any:
    """Клиент эмбеддингов поискового индекса (счётчик query_tokens) или None, если поиск без смысла."""
    embed = getattr(getattr(searcher, "index", None), "embed_query", None)
    return getattr(embed, "__self__", None)


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
    if sc.warm:
        ag.ask(ag.start(vid, sid), sc.turns[0].question)
    conv = ag.start(vid, sid)
    res = Result(sc.key, sc.title)
    emb = _emb_client(searcher)
    for n, turn in enumerate(sc.turns, 1):
        emb_before = emb.query_tokens if emb else 0
        reply = ag.ask(conv, turn.question)
        emb_tokens = (emb.query_tokens if emb else 0) - emb_before
        if emb_tokens:
            rub = emb_tokens * _other("embedding") / 1000
            res.rows.append(
                {"scenario": sc.key, "question": n, "step": 0, "kind": "эмбеддинг", "name": "text-search-query",
                 "tokens_in": emb_tokens, "tokens_cached": 0, "tokens_out": 0, "rub": round(rub, 6), "ms": 0}
            )  # fmt: skip
            res.rub_emb += rub
        for chk in turn.checks:
            bad = chk(reply, conv.vehicle.engine_model)
            if bad:
                res.problems.append(f"вопрос {n}: {bad}")
        for st in reply.trace["steps"]:
            row = {
                "scenario": sc.key,
                "question": n,
                "step": st["step"],
                "kind": {"llm": "модель", "cache": "кэш"}.get(st["kind"], "инструмент"),
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
            rub, what = voice_rub(reply.text, reply.sources)
            res.rows.append(
                {"scenario": sc.key, "question": n, "step": 0, "kind": "речь", "name": what, "tokens_in": 0,
                 "tokens_cached": 0, "tokens_out": 0, "rub": round(rub, 4), "ms": 0}
            )  # fmt: skip
            res.rub_voice += rub
    return res


def write(label: str, results: list[Result], repeat: int, provider: Any = None) -> None:
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
        "provider": getattr(provider, "name", ""),
        "model": getattr(provider, "model", ""),
        "scenarios": {
            r.scenario: {
                "title": r.title,
                "rub": round((r.rub_llm + r.rub_emb) / repeat, 4),  # запрос = модель + эмбеддинг
                "rub_llm": round(r.rub_llm / repeat, 4),
                "rub_emb": round(r.rub_emb / repeat, 6),
                "rub_voice": round(r.rub_voice / repeat, 4),  # опция, не в запросе
                "llm_calls": round(sum(1 for x in r.rows if x["kind"] == "модель") / repeat, 1),
                "llm_ms": sum(x["ms"] for x in r.rows if x["kind"] == "модель") // repeat,
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
    main_runs = [r for r in runs if r.get("provider", "deepseek") == "deepseek"] or runs
    first, last = main_runs[0], main_runs[-1]
    t = price_table()
    lines = [
        "# Себестоимость по участкам (issue #16)",
        "",
        "Все суммы — ₽ без НДС (как в шаблоне организаторов), курс ЦБ на "
        f"{t['usd_rub']['date']}: {t['usd_rub']['value']} ₽/$. Скрипт: `make cost LABEL=…`, шаблон — `make cost-xlsx`.",
        "",
        f"«До» — `{first['label']}`, «после» — `{last['label']}` (DeepSeek). "
        "Строки по шагам — `reports/cost/<замер>.csv`.",
        "Карточка проверки (норма / отклонение / сбой) строится кодом: **0 токенов**.",
        "",
        "| Сценарий | Вызовов модели | Токены вход (из кэша) / выход | ₽ до | ₽ после | Качество |",
        "|---|---|---|---|---|---|",
    ]
    for key, sc in last["scenarios"].items():
        before = first["scenarios"].get(key, {})
        q = "✅" if not sc["problems"] else "❌ " + "; ".join(sc["problems"])
        toks = f"{sc['tokens_in']} ({sc['tokens_cached']}) / {sc['tokens_out']}"
        lines.append(
            f"| {key} — {sc['title']} | {sc['llm_calls']} | {toks} | {before.get('rub', '—')} | {sc['rub']} | {q} |"
        )
    # слои по ответу организаторов 26.11: запрос / разово — индексация / голос — опция / парк в месяц
    fixed = monthly_fixed(last)
    voice = voice_option(last)
    idx = one_time_index()
    fleet = fleet_month(last)
    a, i = ASSUMPTIONS, INDEX
    c1, r1 = last["scenarios"]["С1"], last["scenarios"]["Р1"]
    emb_k = round(other("embedding"), 5)
    lines += [
        "",
        "## Что входит в расчёт (ответ организаторов 26.11)",
        "",
        "> «Эмбеддинги запроса тоже входят. Разовую индексацию руководств посчитайте отдельной строкой. Кроме "
        "стоимости одного сценария, покажите разбивку по шагам и пересчёт на парк. Пример допущения для пересчёта: "
        "50 машин, проверка раз в две недели, два-три вопроса механика на проверку. Допущения назовите явно.»",
        "",
        "| Строка | Количество | Цена без НДС | ₽ | Откуда количество |",
        "|---|---|---|---|---|",
        f"| Запрос С1: модель (шаги — строки 9–11 шаблона) | {c1['llm_calls']} вызова, {c1['tokens_in']} токенов "
        f"на входе ({c1['tokens_cached']} из кэша), {c1['tokens_out']} на выходе | тариф DeepSeek ниже | "
        f"{c1['rub_llm']} | замер `{last['label']}`, среднее {last['repeat']} прогонов |",
        f"| Запрос С1: эмбеддинг запроса (строка 12 шаблона) | {round(c1['rub_emb'] / emb_k * 1000)} токенов | "
        f"{emb_k} ₽ за 1000 | {c1['rub_emb']} | numTokens из ответа Yandex, тот же замер |",
        f"| **Запрос С1, итого** | | | **{c1['rub']}** | `make cost-xlsx` → "
        f"`reports/cost-template-{last['label']}.xlsx` |",
        f"| Разово: OCR страниц без текста | {idx['ocr_pages']} стр. | {round(other('ocr_page'), 4)} ₽ за стр. | "
        f"{idx['ocr_rub']} | страницы меньше 50 знаков (`low_text_pages` паспорта индекса), STATUS «OCR 41 стр.» |",
        f"| Разово: эмбеддинги всех фрагментов | {idx['fragments']} фрагментов × {int(i['chars_per_fragment'])} знаков "
        f"÷ {i['chars_per_token']} знака на токен ≈ {idx['emb_tokens']} токенов | {emb_k} ₽ за 1000 | {idx['emb_rub']} "
        f"({idx['emb_rub_range'][0]}–{idx['emb_rub_range'][1]}) | фрагменты — индекс стенда; длина — сборка без Yandex "
        f"(3 545 фрагментов, 2 234 818 знаков); токен — 3 знака (допущение кода), диапазон 2,5–4 |",
        f"| **Разово, итого** | | | **{idx['rub']}** ({idx['rub_range'][0]}–{idx['rub_range'][1]}) | пересборка "
        "берёт OCR и эмбеддинги из кэша индекса — 0 ₽ |",
        f"| Голос — опция к вопросу | распознавание 15 с + синтез фразы до 250 знаков | SpeechKit, тариф ниже | "
        f"{voice} | правила `src/service/voice.py`; живой замер 0,27 ₽ — `reports/2026-11-26-voice-cost.md` |",
        f"| Парк: запросы в месяц | {int(a['vehicles'])} машин × {round(a['checks_per_vehicle_month'], 2)} проверки "
        f"= {fleet['checks']} проверок × (С1 {c1['rub']} + 1–2 вопроса × Р1 {r1['rub']}) | — | "
        f"{fleet['requests_rub'][0]}–{fleet['requests_rub'][1]} | пример организаторов; сверху: каждая проверка — "
        "отклонение с заявкой (норма и сбой дешевле) |",
        f"| Парк: контейнер и хранилище в месяц | {fixed['questions']} вопросов, {fixed['hours']} ч контейнера, "
        f"{fixed['storage_gb']} ГБ | тарифы ниже | {fleet['fixed_rub']} ({fleet['fixed_rub_no_free_tier']} без "
        "бесплатного уровня) | ниже, «Постоянные» |",
        f"| **Парк в месяц, итого** | | | **{fleet['total_rub'][0]}–{fleet['total_rub'][1]}** | с голосом на каждый "
        f"вопрос +{fleet['voice_rub']} |",
        "",
        "## Слои себестоимости",
        "",
        "1. **Запрос** = модель + эмбеддинг запроса (поиск по смыслу) — таблица выше; только он идёт в строки "
        "шаблона организаторов (`make cost-xlsx`), разовое и парк — в его комментарий.",
        f"2. **Голос — опция** к запросу: распознавание вопроса (15 с) и синтез короткой фразы (SpeechKit, API "
        f"дешевле для её длины) — **+{voice} ₽** на вопрос, округлённо 0,27 ₽ (живой замер — тоже 0,27). Прежние "
        "+1,19 ₽ считали синтез всего ответа по API v1, а приложение озвучивает короткую фразу. "
        f"Альтернатива — {LOCAL_VOICE}.",
        f"3. **Постоянные в месяц на парк** (не в запрос): {fixed['questions']} вопросов в месяц, {fixed['hours']} ч "
        f"работы контейнера ({int(a['vcpu'])} vCPU, {int(a['ram_gb'])} ГБ), хранилище {fixed['storage_gb']} ГБ "
        "(индекс и PDF):",
        f"   - контейнер (Serverless Containers): **{fixed['container_rub']} ₽/мес** в бесплатном уровне, "
        f"{fixed['container_rub_no_free_tier']} ₽/мес без него;",
        f"   - хранилище (Object Storage): **{fixed['storage_rub']} ₽/мес** (первый 1 ГБ бесплатно), "
        f"{fixed['storage_rub_no_free_tier']} ₽/мес без бесплатного объёма;",
        "   - простой подготовленных экземпляров контейнера на странице тарифов без цены — не учтён.",
    ]
    # сравнение моделей: последний замер каждого провайдера
    latest: dict[str, dict[str, Any]] = {}
    for r in runs:
        latest[r.get("provider") or "deepseek"] = r
    if len(latest) > 1:
        keys = list(last["scenarios"])
        lines += [
            "",
            "## Модели: ₽ / время ответа модели / качество (последний замер каждой)",
            "",
            "| Модель | " + " | ".join(keys) + " |",
            "|---|" + "---|" * len(keys),
        ]
        for prov, r in latest.items():
            cells = []
            for k in keys:
                sc = r["scenarios"].get(k)
                if sc is None:
                    cells.append("—")
                    continue
                mark = "✅" if not sc["problems"] else "❌"
                cells.append(f"{sc['rub']} ₽ · {sc.get('llm_ms', 0) / 1000:.1f} с · {mark}")
            lines.append(f"| {prov} `{r.get('model', '')}` (`{r['label']}`) | " + " | ".join(cells) + " |")
        problems = [f"- {prov}, {k}: {'; '.join(sc['problems'])}" for prov, r in latest.items()
                    for k, sc in r["scenarios"].items() if sc["problems"]]  # fmt: skip
        if problems:
            lines += ["", "Провалы проверок качества:", *problems]
    lines += ["", "## Все замеры", "", "| Замер | Модель | " + " | ".join(last["scenarios"]) + " |",
              "|---|---|" + "---|" * len(last["scenarios"])]  # fmt: skip
    for r in runs:
        cells = []
        for k in last["scenarios"]:
            sc = r["scenarios"].get(k)
            cells.append("—" if sc is None else f"{sc['rub']} ₽{'' if not sc['problems'] else ' ❌'}")
        lines.append(f"| `{r['label']}` | {r.get('provider') or 'deepseek'} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Замеры до `7-after-main-merge` посчитаны по прежним ценам (вторичные источники, 100 ₽/$, с НДС у Яндекса),",
        "до `10-layers` — с голосом и оценкой эмбеддинга внутри сценария;",
        "сравнивать их между собой можно, с новыми — только по токенам в CSV.",
        "",
        "## Тарифы (официальные страницы)",
        "",
        "| Участок | Цена | НДС на странице | Источник |",
        "|---|---|---|---|",
    ]
    for name, row in t["llm"].items():
        base = row.get(row.get("use", "")) or row.get("price", {})
        cur = "$" if row["currency"] == "USD" else "₽"
        val = ", ".join(f"{k} {v}{cur}" for k, v in base.items())
        vat = "с НДС" if row["vat_included"] else "без НДС"
        lines.append(f"| модель {name}: {row['model']} | {val} {row['unit']} | {vat} | {row['source']} |")
    for name, row in t["other"].items():
        vat = "с НДС" if row.get("vat_included") else "без НДС"
        lines.append(f"| {name} | {row['value']} {row['unit']} | {vat} | {row['source']} |")
    lines += [f"| курс | {t['usd_rub']['value']} ₽/$ на {t['usd_rub']['date']} | — | {t['usd_rub']['source']} |", ""]
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
            merged.rub_emb += r.rub_emb
            merged.rub_voice += r.rub_voice
            merged.tokens_in += r.tokens_in
            merged.tokens_out += r.tokens_out
            merged.tokens_cached += r.tokens_cached
        results.append(merged)
        tag = "ok" if not merged.problems else "; ".join(merged.problems)
        voice = f" (+ голос {merged.rub_voice / args.repeat:.4f})" if merged.rub_voice else ""
        print(f"{sc.key}: {(merged.rub_llm + merged.rub_emb) / args.repeat:.4f} ₽{voice} — {tag}")
    write(args.label, results, args.repeat, provider)
    print(f"reports/cost/{args.label}.csv, reports/cost.md")
    return 0 if all(not r.problems for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
