"""Совместимость «код неисправности × двигатель» (CLAUDE.md, правило 5).

Если узла у двигателя нет (бензин на дизеле, турбина на атмосферном) — заявку не отправляем.
Источник — матрица по руководствам `data/fault_matrix.json` (issue #10, D-10): несовместимо только то, где
ячейка `applicable == "false"` с проверенной цитатой-основанием. «Не ясно» и «руководство молчит» заявку
не блокируют — их ограничивают ссылки на руководство и подтверждение механика.
"""

from __future__ import annotations

from dataclasses import dataclass

from service.fault_matrix import cell_for


@dataclass(frozen=True)
class Compat:
    ok: bool
    why: str  # пусто, если совместимо
    source: str = ""  # «документ, стр. N» — основание вывода «узла нет»


def check(code: str, engine: str) -> Compat:
    cell = cell_for(code, engine)
    if cell is None or cell.applicable != "false":
        return Compat(True, "")
    src = f"{cell.basis.doc}, стр. {cell.basis.page}" if cell.basis else ""
    return Compat(False, cell.why, src)


def is_compatible(code: str, engine: str) -> bool:
    return check(code, engine).ok
