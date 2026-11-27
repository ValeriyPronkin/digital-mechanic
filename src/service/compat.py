"""Совместимость «код неисправности × двигатель» (CLAUDE.md, правило 5).

Если узла у двигателя нет (бензин на дизеле, турбина на атмосферном) — заявку не отправляем.
Источник — матрица по руководствам `fault_matrix.json` (issue #10, D-10): несовместимо только то, где
ячейка `applicable == "false"` с проверенной цитатой-основанием. Матрицы нет (не опубликована вместе с индексом,
#96) — применимость из её источника `data/fault_matrix.src.json`, по которому она и собрана. «Не ясно» и
«руководство молчит» заявку не блокируют — их ограничивают ссылки на руководство и подтверждение механика.
"""

from __future__ import annotations

from dataclasses import dataclass

from service.fault_matrix import applicability_for


@dataclass(frozen=True)
class Compat:
    ok: bool
    why: str  # пусто, если совместимо
    source: str = ""  # «документ, стр. N» — основание вывода «узла нет»
    doc: str = ""  # основание: документ, страница PDF и цитата (факт о конструкции, issue #40 п. 3)
    page: int = 0
    quote: str = ""


def check(code: str, engine: str) -> Compat:
    cell = applicability_for(code, engine)
    if cell is None or cell.applicable != "false":
        return Compat(True, "")
    if cell.basis is None:
        return Compat(False, cell.why)
    b = cell.basis
    return Compat(False, cell.why, f"{b.doc}, стр. {b.page}", b.doc, b.page, b.quote)


def is_compatible(code: str, engine: str) -> bool:
    return check(code, engine).ok
