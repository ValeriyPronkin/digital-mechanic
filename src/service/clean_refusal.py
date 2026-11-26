"""Чистый отказ (независимый прогон 26.11, п. 5): в 5 из 7 честных отказов агент всё равно приводил рядом числа
с единицами — значения других деталей («нет в руководстве; есть болты распредвала 18,6…22,6 Н·м»). Малоквалифицированный
механик примет их за ответ. Если прямой ответ (первый абзац) — «в руководстве нет», код убирает фразы с числами
и единицами из всего ответа; шаги без чисел (дефектовка, к специалисту) остаются."""

from __future__ import annotations

import re

REFUSAL = re.compile(
    r"не нашёл|не нашел|нет в (?:найденных фрагментах|руководств)|"
    r"в (?:найденных фрагментах|руководств\w*)(?: [а-яё\-.\d ]{0,40})? (?:нет|не указан|не привед|не описан)|"
    r"не указан\w* в руководств|руководств\w* не (?:даёт|дает|указыва|приводит|описыва)",
    re.I,
)
NUM_UNIT = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:(?:…|\.\.\.|[-–—])\s*\d+(?:[.,]\d+)?\s*)?"
    r"(?:мм|см|Н\s*·\s*м|Н\s*м|Нм|кгс|кПа|МПа|бар|атм|°|º|мл|об/мин|мин-1|мин−1|%|Ом|кг|км|л\b|м\b|В\b|А\b|ч\b|с\b)",
    re.I,
)
_SENT = re.compile(r"(?<=[.!?])\s+")
_LIST = re.compile(r"^(\s*(?:\d+[.)]|[-*•])\s+)")
NOTE = "Это отказ: значения других деталей с единицами убрал, чтобы их не приняли за ответ."


def is_refusal(text: str) -> bool:
    first = text.strip().split("\n\n", 1)[0]
    return bool(REFUSAL.search(first))


def clean(text: str) -> tuple[str, bool]:
    """Ответ-отказ без фраз с числами и единицами. → (текст, было ли что убрать)."""
    if not is_refusal(text):
        return text, False
    out, removed = [], False
    for line in text.split("\n"):
        m = _LIST.match(line)
        prefix = m.group(1) if m else ""
        parts = [p for p in _SENT.split(line[len(prefix) :]) if p]
        kept = [p for p in parts if not NUM_UNIT.search(p)]
        removed = removed or len(kept) < len(parts)
        if not parts:
            out.append(line)
        elif kept:
            out.append(prefix + " ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip(), removed
