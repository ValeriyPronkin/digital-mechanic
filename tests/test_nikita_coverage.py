"""Справочник по неисправности из реестра Никиты (registry/coverage.yaml) при SEARCH_ENGINE=nikita."""

from __future__ import annotations

import json
from typing import Any

import pytest

from service.clients import MLClient, ToirClient
from service.nikita import coverage
from test_agent import ANOMALY, INCOMPATIBLE, make_agent, say


def _tool(llm: Any, name: str) -> list[dict[str, Any]]:
    return [json.loads(str(m["content"])) for m in llm.seen[0] if m["role"] == "tool" and m.get("name") == name]


def test_registry_validates_against_our_catalog() -> None:
    reg = coverage.load_registry()
    assert len(reg.engines) == 5 and all(e.operating_limits for e in reg.engines.values())


def test_card_question_gets_guide_without_search(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEARCH_ENGINE", "nikita")
    ag, llm = make_agent([say("ответ")], ml, toir)
    ag.ask(ag.start(*ANOMALY), "Что с двигателем?")
    diag = _tool(llm, "get_diagnosis")[0]
    guide = diag["fault_guide"]
    assert guide["class"] in ("covered", "general_inspection_only") and guide["pages"]
    assert sum(1 for p in guide["pages"] if "text" in p) == min(3, len(guide["pages"]))  # первые три целиком
    assert not any("text" in p for p in guide["operating_limits"])  # пределы — только списком
    assert not _tool(llm, "search_manual")  # страницы — из реестра, поиск не нужен


def test_drive_question_attaches_operating_limits(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEARCH_ENGINE", "nikita")
    ag, llm = make_agent([say("ответ")], ml, toir)
    ag.ask(ag.start(*ANOMALY), "Можно ли ехать своим ходом на базу?")
    guide = _tool(llm, "get_diagnosis")[0]["fault_guide"]
    assert guide["operating_limits"] and all("text" in p for p in guide["operating_limits"])


def test_ours_has_no_guide(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEARCH_ENGINE", raising=False)
    ag, llm = make_agent([say("ответ")], ml, toir)
    ag.ask(ag.start(*ANOMALY), "Что с двигателем?")
    assert "fault_guide" not in _tool(llm, "get_diagnosis")[0]


def test_incompatible_code_no_guide(ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_ENGINE", "nikita")
    ag, llm = make_agent([say("ответ")], ml, toir)
    ag.ask(ag.start(*INCOMPATIBLE), "Что с двигателем?")
    assert "fault_guide" not in _tool(llm, "get_diagnosis")[0]  # совместимость — наша
