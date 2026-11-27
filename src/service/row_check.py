"""Число из соседней строки таблицы (независимый прогон 26.11, самая опасная ошибка): на вопрос о моменте затяжки
одной детали ответ брал число строки про другую деталь той же таблицы — проверка «число есть на странице» его
пропускала. Здесь — проверка на уровне строки: число ответа, которое на странице стоит в строке таблицы, должно
стоять в строке, где названа деталь или параметр из фразы ответа или из вопроса. Иначе фраза снимается.

Строка таблицы = строка страницы, оканчивающаяся числом (или скобкой с числами), + продолжение названия выше
(строки без чисел в конце) + общий заголовок подпунктов «…:» для строк «− …». Число в обычном тексте (не в строке
таблицы) здесь не проверяется — для него остаётся прежняя проверка «число есть во фрагменте».
"""

from __future__ import annotations

import re

from service.manuals.lexical import tokenize

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_ROW_END = re.compile(r"[\d)]\s*$")
_SUB = re.compile(r"^\s*[\-–—•]\s*")
# слова, которые есть почти в каждой строке таблицы моментов и норм — по ним строку не узнать
_GENERIC = {
    "момент", "затяжка", "затягивать", "затянуть", "болт", "гайка", "винт", "шпилька", "крепление", "креплять",
    "крепить", "соединение", "резьбовой", "н", "м", "кгс", "нм", "мм", "мпа", "кпа", "двигатель", "значение",
    "норма", "должный", "который", "какой", "какая", "сила", "основной", "остальной", "весь", "это", "тянуть",
    "приём", "прием", "предварительный", "окончательный", "довернуть", "градус", "руководство", "стр", "страница",
}  # fmt: skip


_REF = re.compile(r"\[\s*[RS]\d+\s*\]")


def _nums(text: str) -> set[str]:
    """Числа от двух цифр; ссылки [R12] — не числа (#90, 27.11: «[R12]» снимало фразу Q16 как «число чужой строки»)."""
    text = _REF.sub(" ", text)
    return {n.replace(",", ".") for n in _NUM.findall(text) if len(n.replace(",", "").replace(".", "")) >= 2}


def distinct(text: str) -> set[str]:
    """Отличительные слова: леммы длиной ≥ 4 без общих слов таблиц."""
    return {t for t in tokenize(text) if len(t) >= 4 and not t[0].isdigit() and t not in _GENERIC}


def rows_with(number: str, page: str) -> list[str] | None:
    """Строки таблицы, где стоит число; None — число на странице не в строке таблицы (не проверяем)."""
    lines = [ln.strip() for ln in page.split("\n")]
    rows: list[str] = []
    in_text = False
    for i, ln in enumerate(lines):
        if number not in _nums(ln):
            continue
        if not _ROW_END.search(ln):
            in_text = True
            continue
        row = [ln]
        j = i - 1
        while j >= 0 and len(row) < 3 and lines[j] and not _ROW_END.search(lines[j]):  # продолжение названия
            row.insert(0, lines[j])
            j -= 1
        if not distinct(" ".join(row)):  # строка без названия («Окончательный момент: 15-17») — название выше
            k = j
            while k >= 0 and k >= i - 6:
                if lines[k] and distinct(lines[k]):
                    head = [lines[k]]
                    m = k - 1
                    while m >= 0 and len(head) < 3 and lines[m] and not _ROW_END.search(lines[m]):
                        head.insert(0, lines[m])
                        m -= 1
                    row = head + row
                    break
                k -= 1
        if _SUB.match(ln):  # подпункт «− …»: общий заголовок выше, до строки с двоеточием
            k = i - 1
            while k >= 0 and k >= i - 8:
                if lines[k].endswith(":"):
                    joined = k > 0 and not _ROW_END.search(lines[k - 1])
                    row.insert(0, f"{lines[k - 1]} {lines[k]}" if joined else lines[k])
                    break
                k -= 1
        rows.append(" ".join(row))
    if not rows or in_text:
        return None  # в обычном тексте число тоже есть — строку таблицы не требуем
    return rows


WEAK_LINES = 2  # слово в ≥ 2 строках страницы («крышка», «головка») строку таблицы не различает


def _weak(page: str) -> set[str]:
    counts: dict[str, int] = {}
    for ln in page.split("\n"):
        for t in distinct(ln):
            counts[t] = counts.get(t, 0) + 1
    return {t for t, c in counts.items() if c >= WEAK_LINES}


def _matches(want: set[str], row: str, weak: set[str]) -> bool:
    words = distinct(row)
    strong = words - weak
    return bool(want & (strong or words))


def row_ok(sentence: str, question: str, pages: list[str]) -> bool:
    """Каждое число фразы, стоящее на странице в строке таблицы, — в строке с деталью из фразы или вопроса
    (по различающим словам строки; общие для многих строк слова не в счёт)."""
    want = distinct(sentence) | distinct(question)
    for n in _nums(sentence):
        checked = [rows_with(n, p) for p in pages]
        if any(c is None and n in _nums(p) for c, p in zip(checked, pages, strict=True)):
            continue  # число есть в обычном тексте страницы
        pairs = [(r, _weak(p)) for c, p in zip(checked, pages, strict=True) if c is not None for r in c]
        if pairs and want and not any(_matches(want, r, weak) for r, weak in pairs):
            return False
    return True
