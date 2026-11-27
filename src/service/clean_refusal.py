"""Чистый отказ (независимый прогон 26.11, п. 5): в 5 из 7 честных отказов агент всё равно приводил рядом числа
с единицами — значения других деталей («нет в руководстве; есть болты распредвала 18,6…22,6 Н·м»). Малоквалифицированный
механик примет их за ответ. Если прямой ответ (первый абзац) — «в руководстве нет», код убирает фразы с числами
и единицами из всего ответа; шаги без чисел (дефектовка) остаются.

Правило заказчика 27.11 (ответ в канале): отказ — правильная основа, но «обратитесь к специалисту» не подходит —
механик сам специалист. Нужно конкретное действие: дефектовка узла и/или ближайший раздел руководства этого двигателя
со страницей (`complete`). Фразы «к специалисту» без ссылки на руководство код убирает из любого ответа."""

from __future__ import annotations

import re

REFUSAL = re.compile(
    r"не нашёл|не нашел|не найден\w*|нет в (?:найденных фрагментах|руководств)|"
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


_SERVICE_LINE = re.compile(r"^\s*(?:\**)(?:Понадобится|Безопасность|Инструмент|Источник)\w*\**\s*:", re.I)


def is_refusal(text: str) -> bool:
    """Прямой ответ — «нет в руководстве»: первый абзац без служебных строк «Понадобится: / Безопасность: …»
    (в них «в руководстве не указано» — про меры безопасности, а не отказ)."""
    paras = [p for p in text.strip().split("\n\n") if p.strip()]
    for p in paras:
        lines = [ln for ln in p.split("\n") if ln.strip() and not _SERVICE_LINE.match(ln)]
        if lines:
            if _LIST.match(lines[0]):
                return False  # сразу шаги — прямого ответа-отказа нет
            return bool(REFUSAL.search(" ".join(lines)))
    return False


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


# «к специалисту», а также отсылка решать к производителю, дилеру, сервису или главному механику (ответ организаторов
# 27.11: механик сам специалист, нужен конкретный шаг — дефектовка узла или раздел руководства)
_SPECIALIST = re.compile(
    r"специалист|(?:обрат|уточн|проконсульт|свяж|запрос|узна)\w*\s+(?:\w+\s+){0,3}?(?:у|к|с|в)\s+"
    r"(?:\w+\s+)?(?:производител|изготовител|завод|дилер|сервис|главн\w* механик)"
    r"|(?:сообщ|доложи|передай)\w*\s+(?:\w+\s+){0,2}?(?:производител|изготовител|завод|дилер|главн\w* механик)"
    r"|через\s+диспетчер",
    re.I,
)
_REF = re.compile(r"\[R\d+\]")


def drop_specialist(text: str) -> tuple[str, bool]:
    """Фразы «к специалисту / уточните у производителя / обратитесь к главному механику» без ссылки [R…] — убрать:
    механик сам специалист. Цитата руководства со ссылкой, где есть слово «специалист», остаётся."""
    out, removed = [], False
    for line in text.split("\n"):
        m = _LIST.match(line)
        prefix = m.group(1) if m else ""
        parts = [p for p in _SENT.split(line[len(prefix) :]) if p]
        kept = [p for p in parts if not (_SPECIALIST.search(p) and not _REF.search(p))]
        removed = removed or len(kept) < len(parts)
        if not parts:
            out.append(line)
        elif kept:
            out.append(prefix + " ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip(), removed


_ACTION = re.compile(r"дефектовк", re.I)
_NEAREST = re.compile(r"ближе всего", re.I)


def complete(text: str, action: str, nearest: str | None) -> tuple[str, list[str]]:
    """Отказ без конкретного действия — дописать: дефектовка узла (`action`) и «ближе всего: раздел, стр. N»
    (`nearest`, если поиск нашёл страницу этого двигателя, а ответ на неё не сослался). → (текст, что дописано)."""
    if not is_refusal(text) or _REF.search(text):  # со ссылками — ответ по руководству, хоть и неполный (eval Q36)
        return text, []
    added: list[str] = []
    if not _ACTION.search(text):
        added.append(action)
    if nearest and not _NEAREST.search(text):
        added.append(nearest)
    if not added:
        return text, []
    return f"{text.rstrip()}\n\n" + "\n".join(added), added


_STEP_KEEP = re.compile(r"дефектовк|повтор\w*\s+(?:проверк|запис)|раздел|не из руководства|предположени", re.I)
_NUMBERED = re.compile(r"^(\s*)(\d+)([.)])(\s+)")


def drop_unsourced_steps(text: str) -> tuple[str, int]:
    """Отказ «в руководстве нет»: пункты списка без ссылки [R…] — порядок работ не из руководства — убрать
    (ответ организаторов 27.11: общие сведения — только с пометкой «не из руководства», без чисел и порядка работ).
    Конкретный шаг (дефектовка, повторная проверка, раздел руководства) и помеченное предположение остаются.
    Нумерация после удаления — подряд."""
    if not is_refusal(text):
        return text, 0
    out, removed = [], 0
    for line in text.split("\n"):
        if _LIST.match(line) and not _REF.search(line) and not _STEP_KEEP.search(line):
            removed += 1
            continue
        out.append(line)
    return renumber("\n".join(out)), removed


def renumber(text: str) -> str:
    """Нумерованный список без пропусков: «1. / 3. / 4.» → «1. / 2. / 3.». Список кончается на строке без номера."""
    out, n = [], 0
    for line in text.split("\n"):
        m = _NUMBERED.match(line)
        if m:
            n += 1
            line = f"{m.group(1)}{n}{m.group(3)}{m.group(4)}{line[m.end() :]}"
        elif line.strip():
            n = 0
        out.append(line)
    return "\n".join(out)
