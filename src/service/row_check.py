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


# Обозначения («ЯМЗ-236М2», «ЯМЗ-5363») и ссылки [R12] — метки, а не числа фразы (стенд 27.11: «236» из «ЯМЗ-236М2»
# искался в строках таблицы и снимал верную фразу про 2100 об/мин)
# То же — каталожные обозначения деталей («236-1007118-В», «7511.1007180»): это не величины, а «236» из них совпадает с
# десятком строк перечня (видео-машина B418HK98, 27.11: снималась верная фраза «втулки коромысел (236-1007118)»)
_LABEL = re.compile(
    r"\b(?:ЯМЗ|ЗМЗ|МАЗ|КамАЗ|ГАЗ|УАЗ)[\s‑–-]*\d[\d.]*(?:[А-ЯA-Z]\d*)*|\[[RS]\d+\]"
    r"|\b\d{2,4}[-.]\d{5,8}(?:-[А-ЯA-Z0-9]{1,3})?(?![\d,])",
    re.I,
)


def _nums(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUM.findall(text) if len(n.replace(",", "").replace(".", "")) >= 2}


def _claim_nums(sentence: str) -> set[str]:
    return _nums(_LABEL.sub(" ", sentence))


def distinct(text: str) -> set[str]:
    """Отличительные слова: леммы длиной ≥ 4 без общих слов таблиц."""
    return {t for t in tokenize(text) if len(t) >= 4 and not t[0].isdigit() and t not in _GENERIC}


def _prose_goes_on(lines: list[str], i: int) -> bool:
    """Строка кончается числом, но это обычный текст: следующая строка продолжает фразу со строчной буквы и сама
    числом не кончается («…усилием 39,2» / «должен быть от 4 до 8 мм.», «…(360» / «градусов).»)."""
    nxt = next((ln for ln in lines[i + 1 :] if ln), "")
    return bool(nxt) and nxt[0].islower() and not _ROW_END.search(nxt)


def rows_with(number: str, page: str) -> list[str] | None:
    """Строки таблицы, где стоит число; None — число на странице не в строке таблицы (не проверяем)."""
    lines = [ln.strip() for ln in page.split("\n")]
    rows: list[str] = []
    in_text = False
    for i, ln in enumerate(lines):
        if number not in _nums(ln):
            continue
        if not _ROW_END.search(ln) or _prose_goes_on(lines, i):
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
        if not distinct(" ".join(row)):  # значение без названия (колонка таблицы по моделям) — строку не узнать
            continue
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


# фраза «в руководстве этого нет» числа со страницы не утверждает — повторяет вопрос («расход AdBlue на 100 л … в
# руководстве не нашёл»); строку таблицы для неё не ищем
_NO_DATA = r"(?:не\s+наш[её]л|не\s+найден\w*|не\s+указан\w*|не\s+привод\w*|нет)"
_ABSENT = re.compile(
    rf"(?:руководств|фрагмент)\w*[^.!?]{{0,80}}?\b{_NO_DATA}\b"
    rf"|\b{_NO_DATA}\b[^.!?]{{0,80}}?(?:руководств|фрагмент)",
    re.I,
)


def _table_words(page: str) -> set[str]:
    """Различающие слова строк таблиц страницы: строка, кончающаяся числом, и до двух строк названия над ней."""
    lines = [ln.strip() for ln in page.split("\n")]
    out: set[str] = set()
    for i, ln in enumerate(lines):
        if ln and _ROW_END.search(ln) and not _prose_goes_on(lines, i):
            out |= distinct(" ".join(lines[max(0, i - 2) : i + 1]))
    return out


def _whole_range(want: set[str], row: str, page: str, nums: set[str]) -> bool:
    """Фраза повторяет диапазон строки целиком (в строке ≥ 2 числа фразы), строка совпадает с фразой или вопросом
    хотя бы по двум словам (пусть и общим для страницы), а другой строки таблицы фраза и вопрос не называют.
    Так проходит «от 130,00 до 130,02 мм» внутреннего диаметра гильзы и «1300…1600 мин⁻¹» при максимальном моменте,
    где все слова строки есть и в соседних строках; «430-470» для «крышек шатунов» по-прежнему снимается."""
    words = distinct(row)
    if len(nums & _nums(row)) < 2 or len(want & words) < 2:
        return False
    return not (want & (_table_words(page) - _weak(page)) - words)


def row_ok(sentence: str, question: str, pages: list[str]) -> bool:
    """Каждое число фразы, стоящее на странице в строке таблицы, — в строке с деталью из фразы или вопроса
    (по различающим словам строки; общие для многих строк слова не в счёт)."""
    want = distinct(sentence) | distinct(question)
    if _ABSENT.search(sentence):
        return True
    nums = _claim_nums(sentence)
    for n in nums:
        checked = [rows_with(n, p) for p in pages]
        if any(c is None and n in _nums(p) for c, p in zip(checked, pages, strict=True)):
            continue  # число есть в обычном тексте страницы
        found = [(r, p) for c, p in zip(checked, pages, strict=True) if c is not None for r in c]
        if not found or not want:
            continue
        if any(_matches(want, r, _weak(p)) or _whole_range(want, r, p, nums) for r, p in found):
            continue
        return False
    return True
