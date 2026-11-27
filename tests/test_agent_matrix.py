"""Агент и матрица «код × двигатель» (issue #10): работы и ссылки заявки — из подтверждённой ячейки."""

from __future__ import annotations

import json

import pytest

from matrix_fixture import NO_MATRIX
from service.clients import MLClient, ToirClient
from service.fault_matrix import cell_for, matrix_loaded
from service.llm import Message
from service.manuals.catalog import documents_for_engine
from test_agent import EmptySearch, call, first, make_agent, say

if not matrix_loaded():  # ниже на импорте ищутся проверки с подтверждённой и «молчащей» ячейкой
    pytest.skip(NO_MATRIX, allow_module_level=True)


def _status(v: object, s: object, status: str) -> bool:
    code, engine = getattr(s, "anomaly_type", None), getattr(v, "engine_model", "")
    cell = cell_for(code, engine) if code else None
    return (
        getattr(s, "status", "") == "anomaly"
        and getattr(s, "signal_quality", "") == "good"
        and cell is not None
        and cell.status == status
    )


CONFIRMED = first(lambda v, s: _status(v, s, "confirmed"))
SILENT = first(lambda v, s: _status(v, s, "silent"))


def _tool_result(messages: list[Message], name_hint: str) -> dict[str, object]:
    for m in reversed(messages):
        if m.get("role") == "tool" and name_hint in str(m.get("content", "")):
            content = str(m["content"])
            return dict(json.loads(content[content.index("{") : content.rindex("}") + 1]))
    raise AssertionError(f"нет ответа инструмента с {name_hint}")


def test_ticket_takes_operations_and_pages_from_confirmed_cell(ml: MLClient, toir: ToirClient) -> None:
    vid, sid = CONFIRMED
    steps = [
        call("get_diagnosis", vehicle_id=vid, session_id=sid),
        call("draft_ticket", conclusion="Неисправность по результату проверки"),
        say("Черновик готов [R1]."),
    ]
    ag, llm = make_agent(steps, ml, toir, EmptySearch())  # поиск пуст: всё — из матрицы
    conv = ag.start(vid, sid)
    reply = ag.ask(conv, "Оформи заявку")
    assert reply.draft is not None, reply.text
    body = reply.draft["body"]
    cell = cell_for(body["anomaly_type"], conv.vehicle.engine_model)
    assert cell is not None and cell.status == "confirmed"
    assert body["operations"] == [o.quote for o in cell.operations]
    own = {d.designation for d in documents_for_engine(conv.vehicle.engine_model)}
    assert body["references"] and {r["manual"] for r in body["references"]} <= own
    cell_pages = {r.page for r in [*cell.pages, *cell.operations]}
    assert {r["pdf_page"] for r in body["references"]} <= cell_pages

    diag = _tool_result(llm.seen[1], "manual_matrix")
    matrix = diag["manual_matrix"]
    assert isinstance(matrix, dict) and matrix["status"] == "confirmed"


def test_silent_cell_tells_to_send_for_defect_inspection(ml: MLClient, toir: ToirClient) -> None:
    vid, sid = SILENT
    steps = [
        call("get_diagnosis", vehicle_id=vid, session_id=sid),
        call("draft_ticket", conclusion="Неисправность"),
        say("В руководстве не нашёл — нужна дефектовка."),
    ]
    ag, llm = make_agent(steps, ml, toir, EmptySearch())
    reply = ag.ask(ag.start(vid, sid), "Оформи заявку")
    assert reply.draft is None  # ни работ, ни ссылок из руководства — заявки нет
    diag = _tool_result(llm.seen[1], "manual_matrix")
    matrix = diag["manual_matrix"]
    assert isinstance(matrix, dict) and matrix["status"] == "silent" and matrix["note"]
    refused = _tool_result(llm.seen[2], "refused")
    assert "ссылок" in str(refused["refused"])
