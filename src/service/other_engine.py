"""Вопрос про ДРУГОЙ двигатель (независимый прогон 26.11): «а у ЯМЗ-7511…», «у ЯМЗ-238…» — агент отвечал цифрами
двигателя своей машины. Модель в вопросе распознаёт код; не совпала с двигателем машины — чистый отказ без цифр:
отвечаем только по руководствам двигателя этой машины (CLAUDE.md, правило 3)."""

from __future__ import annotations

import re

from service.manuals.catalog import ENGINES, _norm, canonical_engine

# Модель двигателя — только с маркой: «236-1007118» (обозначение детали) и «МАЗ-5337» (машина) — не двигатель
MENTION = re.compile(
    r"(?<![\w-])(?:(?:ЯМЗ|ЗМЗ|УМЗ|ММЗ|ТМЗ|YAMZ|ZMZ)\s*[-–]?\s*\d{2,5}(?:[.,]\d+)?[А-ЯA-Zа-я]{0,2}\d?"
    r"|(?:КамАЗ|КАМАЗ)\s*[-–]?\s*7\d{2,3}(?:[.,]\d+)?"
    r"|Д\s*[-–]\s*2\d{2}(?:[.,]\d+)?|Cummins(?:\s+[A-Z]{2,4}\d*\.?\d*)?|Камминз)(?![\w])",
    re.I,
)


def mentions(question: str) -> list[str]:
    return list(dict.fromkeys(" ".join(m.group(0).split()) for m in MENTION.finditer(question)))


def _same(name: str, vehicle_engine: str) -> bool:
    """Та же модель или её семейство без модификации («ЗМЗ-409» у ЗМЗ-40904.10, «ЯМЗ-236» у ЯМЗ-236М2)."""
    canon = canonical_engine(name)
    own = canonical_engine(vehicle_engine) or vehicle_engine
    if canon is not None:
        return canon == own
    n, o = _norm(name), _norm(own)
    if len(n) < len("ЗМЗ409"):
        return False
    # семейство без модификации («ЗМЗ-409» у ЗМЗ-40904.10) или модификация своего семейства («ЯМЗ-5361» у ЯМЗ-536 —
    # то же руководство; модификации — отдельная задача)
    return o.startswith(n) or n.startswith(o.split(".")[0])


def other(question: str, vehicle_engine: str) -> str | None:
    """Первая модель из вопроса, которая не двигатель этой машины, или None."""
    return next((m for m in mentions(question) if not _same(m, vehicle_engine)), None)


def answer(name: str, vehicle_id: str, vehicle_engine: str) -> str:
    in_base = canonical_engine(name)
    if in_base is not None and in_base in ENGINES:
        return (
            f"**Вопрос про {name}, а у машины {vehicle_id} двигатель {vehicle_engine}.** Отвечаю только по "
            f"руководствам двигателя этой машины. Чтобы спросить про {in_base}, откройте машину с этим двигателем."
        )
    return (
        f"**Руководств на {name} в базе нет.** По машине {vehicle_id} (двигатель {vehicle_engine}) могу ответить — "
        "спросите про её двигатель."
    )
