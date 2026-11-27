"""Карточка вердикта по ответу /diagnose. Чистый код, без модели (CLAUDE.md, «Правила», п. 1, 2, 7).

Решения принимаются только по полям `status`, `anomaly_type`, `anomaly_score`, `confidence`,
`signal_quality`. Поле `description` — данные ML-сервиса: оно попадает в карточку только как цитата
(`ml_quote`) и не участвует ни в одном условии ниже.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from service.clients import Diagnosis
from service.compat import check as compat_check
from service.manuals.catalog import DOCS_BY_ID

EARLY_RECHECK_SCORE = 0.30

Color = Literal["green", "yellow", "red", "grey"]

BANNER_NOISY = "Запись с помехами, уверенность снижена."
BANNER_BAD = "Запись непригодна для выводов."
BANNER_EARLY_RECHECK = "Норма, но повторите проверку раньше срока."


Urgency = Literal["low", "medium", "high"]
URGENCY_RU = {"high": "высокая", "medium": "средняя", "low": "низкая"}
BANNER_CONFIRM = "Подтвердите повторной записью. Приоритет остаётся высоким: неисправность опасна для двигателя."
_DANGER = json.loads((Path(__file__).resolve().parents[2] / "data" / "danger_classes.json").read_text(encoding="utf-8"))
SCORE_HIGH = float(_DANGER["score_high"])
CONFIDENCE_LOW = float(_DANGER["confidence_low"])
_TITLES = {
    f["code"]: f["title"]
    for f in json.loads((Path(__file__).resolve().parents[2] / "data" / "fault_types.json").read_text(encoding="utf-8"))
}
# Класс 3 — работа двигателя грозит разрушением: срочность высокая независимо от оценки (data/danger_classes.json).
CRITICAL_CODES = {c: v["basis"] for c, v in _DANGER["classes"].items() if v["class"] == 3}


def danger_class(code: str) -> int | None:
    v = _DANGER["classes"].get(code)
    return int(v["class"]) if v else None


def _num(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def risk_line(code: str) -> str:
    """Чем грозит неисправность — по классу опасности (data/danger_classes.json). Это оценка инженера, а не текст
    руководства, поэтому так и подписано; запрета эксплуатации здесь нет."""
    basis = _DANGER["classes"].get(code, {}).get("basis")
    return f"Чем грозит (оценка инженера, не из руководства): {basis}" if basis else ""


def preliminary(diag: Diagnosis) -> bool:
    """Вывод предварительный: уверенность модели ниже порога или запись с помехами."""
    return (diag.confidence or 0) < CONFIDENCE_LOW or diag.signal_quality == "warning"


_STEPS: tuple[Urgency, ...] = ("low", "medium", "high")
_BASE: dict[int, Urgency] = {1: "low", 2: "medium", 3: "high"}


def _urgency_rule(diag: Diagnosis) -> tuple[Urgency, str]:
    """Срочность — правило в коде, с основанием простыми словами (подписано инженером, наше решение №86):
    базовый уровень по классу опасности; высокая оценка поднимает не больше чем на ступень, класс 1 («двигателю
    не грозит») — не выше среднего; предварительный вывод не поднимает и опускает на ступень, кроме класса 3.
    Одно и то же для карточки, заявки и сводки парка. Название неисправности здесь не повторяется."""
    code = diag.anomaly_type or ""
    cls = danger_class(code) or 2
    score = diag.anomaly_score or 0
    if cls == 3:
        return "high", f"Опасная неисправность: {CRITICAL_CODES[code]}"
    base = _STEPS.index(_BASE[cls])
    if preliminary(diag):
        pct, low = round((diag.confidence or 0) * 100), round(CONFIDENCE_LOW * 100)
        noisy = diag.signal_quality == "warning"
        why = "Запись с помехами" if noisy else f"Уверенность модели {pct}\u00a0%, порог {low}\u00a0%"
        return _STEPS[max(base - 1, 0)], f"{why}: сначала повторить запись или провести дефектовку"
    if score >= SCORE_HIGH:
        top = 1 if cls == 1 else 2
        level = _STEPS[min(base + 1, top)]
        cap = ", для этого класса не выше среднего" if cls == 1 else ""
        return level, f"Оценка отклонения {_num(score)}, порог {_num(SCORE_HIGH)}: на ступень выше{cap}"
    return _STEPS[base], f"Оценка отклонения {_num(score)} ниже порога {_num(SCORE_HIGH)}"


def urgency_for(diag: Diagnosis) -> tuple[Urgency, str]:
    """Приоритет и его основание; кроме класса 3 (там угроза уже в основании) — ещё и чем грозит неисправность."""
    urgency, reason = _urgency_rule(diag)
    code = diag.anomaly_type or ""
    risk = risk_line(code) if danger_class(code) != 3 else ""
    return urgency, f"{reason}. {risk}" if risk else reason


def trend_for(history: list[Any], session_id: str) -> str | None:
    """Тенденция по истории ТС (issue #40 п. 4): оценка растёт хотя бы вторую проверку подряд — «0,06 → 0,20 → 0,85».
    Только проверки до текущей включительно и только пригодные (без check_failed и записи «bad»)."""
    ordered = sorted(history, key=lambda s: s.checked_at)
    upto = []
    for s in ordered:
        if s.status != "check_failed" and s.signal_quality != "bad" and s.anomaly_score is not None:
            upto.append(s)
        if s.session_id == session_id:
            break
    else:
        return None
    if not upto or upto[-1].session_id != session_id:
        return None
    run = [upto[-1].anomaly_score]
    for s in reversed(upto[:-1]):
        if s.anomaly_score < run[0]:
            run.insert(0, s.anomaly_score)
        else:
            break
    if len(run) < 3:
        return None
    seq = ", ".join(_num(x) for x in run)
    times = {2: "вторую", 3: "третью", 4: "четвёртую"}.get(len(run) - 1, f"{len(run) - 1}-ю")
    return f"Оценка отклонения растёт {times} проверку подряд: {seq}."


URGENCY_ACTION = {
    # Значения приоритетов — ответ организаторов 26.11. Запрет эксплуатации здесь не пишется: он бывает только
    # словами руководства на этот двигатель и со страницей.
    "high": "Поставить на дефектовку до выпуска в рейс. Оформите заявку.",
    "medium": "Дефектовка на ближайшем ТО, до него машина работает под наблюдением. Оформите заявку.",
    "low": "Машина работает, узел проверить на следующей проверке. Заявку можно оформить.",
}


class VerdictCard(BaseModel):
    status: Literal["normal", "anomaly", "check_failed"]
    color: Color
    title: str
    action: str
    banners: list[str]
    ticket_possible: bool
    compatible: bool = True  # код совместим с двигателем ТС (правило 5)
    fault_code: str | None
    fault_title: str | None
    confidence_pct: int | None
    ml_quote: str  # цитата ML-сервиса как есть; показывать как текст, не исполнять
    ml_quote_label: str
    # Посторонний текст в описании сервиса (инструкции «ассистенту», «верни статус», «выведи промпт»): показывается
    # отдельно, серым — «отложен», чтобы было видно, что из данных ничего не исполнено (#40 п. 6). Только для показа:
    # в условиях карточки не участвует, модели не передаётся.
    ml_injection: str | None = None
    manual: dict[str, Any] | None = None  # пояснение из матрицы по руководству (#16), без модели
    urgency: Urgency | None = None  # срочность по правилу urgency_for (как в заявке)
    urgency_reason: str | None = None
    danger_class: int | None = None  # класс опасности кода 1–3 (data/danger_classes.json)
    trend: str | None = None  # тенденция по истории ТС: «оценка растёт вторую проверку подряд: …»
    passport: dict[str, Any] | None = None  # «?» у карточки (#31): что сделал код, 0 токенов
    design_fact: dict[str, Any] | None = None  # несовместимый код: факт о конструкции с цитатой (issue #40 п. 3)


def _design_fact(compat: Any) -> dict[str, Any] | None:
    """Факт о конструкции из ячейки матрицы «узла нет»: что именно отсутствует и цитата-основание со страницей."""
    if not compat.doc:
        return None
    doc = DOCS_BY_ID.get(compat.doc)
    return {
        "text": compat.why[:1].upper() + compat.why[1:] + ".",
        "quote": compat.quote,
        "manual": doc.designation if doc else compat.doc,
        "pdf_page": compat.page,
        "url": f"/manuals/{compat.doc}#page={compat.page}",
    }


def _pct(value: float | None) -> int | None:
    return None if value is None else round(value * 100)


# Признаки текста, обращённого к системе или ассистенту, а не к механику: обращения и команды про статус, заявку,
# промпт и инструкции. С первого такого предложения и до конца описание считается посторонним.
_INJECTION = re.compile(
    r"\bsystem\b\s*:|\bassistant\b|ассистент|\bai[-\s]?агент|\bии[-\s]?агент|\bagent\b|нейросет|языков\w*\s+модел"
    r"|инструкци\w*\s+(?:для|отмен)|предыдущ\w*\s+инструкц|игнорир|проигнорир|ignore\s+(?:all|previous)"
    r"|системн\w*\s+промпт|\bprompt\b|промпт|верн\w*\s+статус|\bstatus\s*=|ticket_possible|\bвыведи\b"
    r"|сообщи\s+механику|заявку\s+не\s+созда|создай\s+заявку|считать\s+проверку\s+пройденн|<\s*/?\s*script",
    re.IGNORECASE,
)


def find_injection(description: str) -> str | None:
    """Посторонний текст в описании сервиса диагностики: от первого предложения-обращения к системе до конца."""
    parts = [p for p in re.split(r"(?<=[.!?;])\s+", (description or "").strip()) if p]
    for i, part in enumerate(parts):
        if _INJECTION.search(part):
            return " ".join(parts[i:])
    return None


def build_card(
    diag: Diagnosis, fault_titles: dict[str, str], engine: str | None = None, history: list[Any] | None = None
) -> VerdictCard:
    card = _build_card(diag, fault_titles, engine)
    card.ml_injection = find_injection(diag.description)
    if history and card.status != "check_failed" and card.color != "grey":
        card.trend = trend_for(history, diag.session_id)
    return card


def _build_card(diag: Diagnosis, fault_titles: dict[str, str], engine: str | None = None) -> VerdictCard:
    banners: list[str] = []
    if diag.signal_quality == "warning":
        banners.append(BANNER_NOISY)

    if diag.status == "check_failed" or diag.signal_quality == "bad":
        # Никаких выводов о двигателе: ни кода, ни уверенности, ни заявки.
        return VerdictCard(
            status=diag.status,
            color="grey",
            title="Проверка не удалась",
            action="Выводов о двигателе нет. Повторите запись звука: прогрейте двигатель, "
            "дождитесь ровного холостого хода и запишите снова.",
            banners=[BANNER_BAD] if diag.status != "check_failed" else [],
            ticket_possible=False,
            fault_code=None,
            fault_title=None,
            confidence_pct=None,
            ml_quote=diag.description,
            ml_quote_label="Причина отбраковки (сообщение сервиса диагностики)",
        )

    if diag.status == "normal":
        early = diag.anomaly_score is not None and diag.anomaly_score >= EARLY_RECHECK_SCORE
        if early:
            banners.append(BANNER_EARLY_RECHECK)
        return VerdictCard(
            status="normal",
            color="yellow" if early else "green",
            title="Двигатель в норме",
            action="Можно продолжать работу. Заявка не нужна."
            + (" Сделайте повторную проверку раньше планового срока." if early else ""),
            banners=banners,
            ticket_possible=False,
            fault_code=None,
            fault_title=None,
            confidence_pct=_pct(diag.confidence),
            ml_quote=diag.description,
            ml_quote_label="Сообщение сервиса диагностики",
        )

    # anomaly: название — из нашего справочника по коду, а не из текста ответа.
    code = diag.anomaly_type
    title = fault_titles.get(code) if code else None
    known = title is not None
    if known and code and engine:
        compat = compat_check(code, engine)
        if not compat.ok:
            return VerdictCard(
                status="anomaly",
                color="grey",
                title="Результат не подходит к этому двигателю",
                action=f"Сервис указал «{title}», но {compat.why} ({engine}). "
                "Скорее всего, ошибка записи: повторите проверку. Заявку по такому результату не оформляем.",
                banners=banners,
                ticket_possible=False,
                compatible=False,
                fault_code=code,
                fault_title=title,
                confidence_pct=_pct(diag.confidence),
                ml_quote=diag.description,
                ml_quote_label="Сообщение сервиса диагностики",
                design_fact=_design_fact(compat),
            )
    urgency, reason = urgency_for(diag) if known else (None, None)
    if known and code and danger_class(code) == 3 and diag.signal_quality == "warning":
        banners.append(BANNER_CONFIRM)  # плашка «с помехами» остаётся (приёмка: 17 warning с плашкой)
    return VerdictCard(
        status="anomaly",
        color="red",
        title=f"{'Предварительно' if preliminary(diag) else 'Вероятно'}: {title[:1].lower()}{title[1:]}"
        if known and title
        else "Неисправность неизвестного типа",
        action=URGENCY_ACTION[urgency]
        if urgency
        else "Тип неисправности не распознан. Повторите проверку; заявку по такому результату не оформляем.",
        urgency=urgency,
        urgency_reason=reason,
        danger_class=danger_class(code) if known and code else None,
        banners=banners,
        ticket_possible=known,
        fault_code=code if known else None,
        fault_title=title,
        confidence_pct=_pct(diag.confidence),
        ml_quote=diag.description,
        ml_quote_label="Сообщение сервиса диагностики",
    )
