"""Страница продолжается на соседней (разбор стабильных провалов открытой половины, 27.11).

Таблица неисправностей, перечень деталей, порядок работ часто идут через границу страницы. Поиск находит одну
страницу, а нужная строка — на соседней: «вкладыши» в продолжении таблицы стуков (Q15), уплотняющая шайба на
соседней странице перечня (Q16), порядок работы цилиндров — пункт 7 на следующей странице после пунктов 1–6 (Q03).
Признаки продолжения — по тексту страниц, без привязки к вопросу (приём `_neighbours` Никиты, расширенный):
  - следующая страница начинается с «Продолжение таблицы» / «(Продолжение)»;
  - следующая страница начинается с той же шапки таблицы, что есть на этой («Причина неисправности Метод устранения»);
  - нумерованный порядок: последний пункт этой страницы N, а следующая начинается с пункта N+1;
  - текст этой страницы обрывается: последняя строка кончается двоеточием, запятой, точкой с запятой или переносом;
  - текст следующей страницы начинается со строчной буквы — предложение перешло через границу («…согласно
    перечислениям а) и б) в | порядке работы цилиндров: 1–4–2–5–3–6», РК ЯМЗ-236 стр. 254–255, Q03).
"""

from __future__ import annotations

import re

HEAD_LINES = 5
_PAGE_NO = re.compile(r"^\s*\d{1,4}\s*$")
_CONTINUED = re.compile(r"продолжение", re.I)
_STEP = re.compile(r"^\s*(\d{1,2})\s*[.)]\s+\S")
_HAS_LETTER = re.compile(r"[A-Za-zА-Яа-яЁё]")
_CAPTION = re.compile(r"^\s*(?:рис|рисунок|табл|таблица)\.?\s*\d", re.I)
_OPEN_END = re.compile(r"(?:[:,;]|[а-яё]-)$")


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not _PAGE_NO.match(ln)]


def _head(text: str) -> list[str]:
    return _lines(text)[:HEAD_LINES]


def continues(page: str, nxt: str) -> bool:
    """Текст `page` продолжается на следующей странице `nxt`."""
    head = _head(nxt)
    if not head:
        return False
    if any(_CONTINUED.search(ln) for ln in head[:3]):
        return True
    lines = _lines(page)
    # повтор шапки таблицы: первая строка следующей страницы — строка-шапка, которая есть и на этой
    if len(head[0]) >= 15 and not _STEP.match(head[0]) and head[0] in lines:
        return True
    steps = [int(m.group(1)) for ln in lines if (m := _STEP.match(ln))]
    first = next((int(m.group(1)) for ln in head if (m := _STEP.match(ln))), None)
    if steps and first is not None and first == steps[-1] + 1 and first > 1:
        return True
    first_text = next((ln for ln in head if _HAS_LETTER.search(ln)), "")
    if first_text[:1].islower():
        return True
    text = [ln for ln in lines if _HAS_LETTER.search(ln) and not _CAPTION.match(ln)]
    return bool(text) and bool(_OPEN_END.search(text[-1]))
