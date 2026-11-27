"""Тексты, которые видит механик, — по правилам docs/copy-rules.md (`service.copy_lint`).

Что проверяется:
- `web/src/copy.ts`: строковые и шаблонные литералы (комментарии, ключи и импорты пропускаются; `${…}` заменяется
  образцом);
- строки сервера на карточке, в строке парка и в ответе про чужой двигатель: они проверяются как выходы функций
  (`urgency_for`, `trend_for`, `other_engine.answer`, `vehicle_status`), а не как куски исходника;
- README: проза построчно, без кода, ссылок и HTML. Пока README переписывает поток «жюри» (#105), этот тест
  помечен как ожидаемо падающий.

Не проверяется: тексты, которые пишет модель, и строки `src/service/agent.py` (первое лицо, «помощник») — их правит
поток «доверие». TODO: включить `agent.py` и ответы модели (eval), когда поток «доверие» сольётся.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from service import other_engine
from service.clients import Diagnosis
from service.copy_lint import violations
from service.verdict_policy import (
    BANNER_BAD,
    BANNER_CONFIRM,
    BANNER_EARLY_RECHECK,
    BANNER_NOISY,
    URGENCY_ACTION,
    trend_for,
    urgency_for,
)

ROOT = Path(__file__).resolve().parent.parent
COPY_TS = ROOT / "web" / "src" / "copy.ts"
README = ROOT / "README.md"
SAMPLE = "12"


def ts_literals(source: str) -> Iterator[tuple[int, str]]:
    """(строка, текст) каждого строкового и шаблонного литерала-значения; `${…}` заменён образцом."""
    i = 0
    while i < len(source):
        ch = source[i]
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = len(source) if end < 0 else end
        elif source.startswith("/*", i):
            i = source.index("*/", i) + 2
        elif ch in "'\"`":
            start, parts = i, []
            i += 1
            while source[i] != ch:
                if source[i] == "\\":
                    parts.append(source[i + 1])
                    i += 2
                elif ch == "`" and source.startswith("${", i):
                    i = source.index("}", i) + 1
                    parts.append(SAMPLE)
                else:
                    parts.append(source[i])
                    i += 1
            i += 1
            before = source[source.rfind("\n", 0, start) + 1 : start]
            is_key = source[i:].lstrip().startswith(":") and before.rstrip()[-1:] in ("", "{", ",")
            if not is_key and not re.search(r"(\bfrom|\bimport)\s*$", before):
                yield source.count("\n", 0, start) + 1, "".join(parts)
        else:
            i += 1


def diagnosis(**kw: object) -> Diagnosis:
    base: dict[str, object] = {
        "vehicle_id": "A427MA78",
        "session_id": "S-0032",
        "status": "anomaly",
        "anomaly_type": "F01",
        "anomaly_title": "Клапанный механизм",
        "anomaly_score": 0.7,
        "confidence": 0.9,
        "signal_quality": "good",
        "description": "",
        "model_version": "mock-v1",
    }
    return Diagnosis.model_validate(base | kw)


def server_texts() -> list[tuple[str, str]]:
    """Строки сервера, которые механик видит на карточке и в строке парка, — каждая ветка правила."""
    texts = [(f"BANNER {t}", t) for t in (BANNER_NOISY, BANNER_BAD, BANNER_EARLY_RECHECK, BANNER_CONFIRM)]
    texts += [(f"URGENCY_ACTION[{k}]", v) for k, v in URGENCY_ACTION.items()]
    branches = {
        "класс 3": diagnosis(anomaly_type="F02", anomaly_title="Низкое давление масла"),
        "оценка выше порога": diagnosis(anomaly_score=0.93),
        "низкая уверенность": diagnosis(confidence=0.4),
        "помехи": diagnosis(signal_quality="warning"),
        "класс 1": diagnosis(anomaly_type="F05", anomaly_title="Генератор"),
        "средний": diagnosis(),
    }
    texts += [(f"urgency_for: {name}", urgency_for(d)[1]) for name, d in branches.items()]
    history = [
        SimpleNamespace(
            session_id=f"S{i}", checked_at=f"2026-1{i}", status="anomaly", signal_quality="good", anomaly_score=s
        )
        for i, s in enumerate((0.06, 0.2, 0.85))
    ]
    texts.append(("trend_for", trend_for(history, "S2") or ""))
    plate = "А427МА78"  # госномер — данные парка, не текст продукта; образец кириллицей
    texts.append(("other_engine: в базе", other_engine.answer("ЯМЗ-536", plate, "ЯМЗ-236М2")))
    texts.append(("other_engine: нет в базе", other_engine.answer("ЯМЗ-7511", plate, "ЯМЗ-236М2")))
    return texts


def markdown_prose(markdown: str) -> Iterator[tuple[int, str]]:
    not_prose = re.compile(r"<!--.*?-->|`[^`]*`|!\[[^\]]*\]\([^)]*\)|(?<=\])\([^)]*\)|<[^>]+>|https?://\S+")
    fenced = False
    for number, line in enumerate(markdown.splitlines(), start=1):
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
        elif not fenced and re.search(r"\w", prose := not_prose.sub("", line)):
            yield number, prose.strip()


def lint(texts: list[tuple[str, str]]) -> list[str]:
    out = []
    for where, text in texts:
        for v in violations(text):
            rule = f"{v.rule} /{v.pattern}/" if v.pattern else v.rule
            out.append(f"{where}: «{v.fragment}» [{rule}] → {v.suggestion}")
    return out


def test_copy_ts() -> None:
    source = COPY_TS.read_text(encoding="utf-8")
    texts = [(f"web/src/copy.ts:{n}", t) for n, t in ts_literals(source) if re.search(r"[А-Яа-яЁё]", t)]
    assert texts, "сканер не нашёл строк в copy.ts"
    assert lint(texts) == []


def test_server_texts_on_card_and_fleet() -> None:
    assert lint(server_texts()) == []


@pytest.mark.xfail(reason="README переписывает поток «жюри» (#105); после слияния снять отметку", strict=False)
def test_readme_prose() -> None:
    texts = [(f"README.md:{n}", t) for n, t in markdown_prose(README.read_text(encoding="utf-8"))]
    assert lint(texts) == []


def test_lint_catches_what_it_should() -> None:
    """Правила действительно читаются: запрет без страницы, отсылка к специалисту, «я» — ловятся."""
    for bad in ("Срочно!!! Обратитесь к специалисту.", "Я нашёл ответ.", "Решение за главным механиком."):
        assert violations(bad), bad
