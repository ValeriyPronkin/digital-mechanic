"""read_pages Никиты (app/tools/manual.py) при SEARCH_ENGINE=nikita: страницы целиком, соседние — сами."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, ClassVar

import pytest

from service.agent import tools
from service.clients import MLClient, ToirClient
from service.fleet import fleet
from service.manuals.catalog import canonical_engine, documents_for_engine
from service.nikita import pages, read, search
from test_agent import ANOMALY, call, make_agent, say


@dataclass
class Frag:
    doc_id: str
    page: int
    text: str
    section: str = ""
    source: str = "PDF"


ENGINE = canonical_engine(next(v.engine_model for v in fleet().vehicles if v.vehicle_id == ANOMALY[0])) or ""
DOC = documents_for_engine(ENGINE)[0]
OTHER = next(d for d in documents_for_engine("ЗМЗ-40904.10"))


class FakeIndex:
    fragments: ClassVar[list[Frag]] = [
        Frag(DOC.doc_id, 10, "Проверка давления масла\nДавление масла 4,0 кгс/см2\nПорядок проверки:", "Смазка"),
        Frag(DOC.doc_id, 11, "1. Подсоединить манометр.\n2. Пустить двигатель."),
        Frag(DOC.doc_id, 20, "Таблица 3\nМомент затяжки 120 Н·м"),
        Frag(DOC.doc_id, 21, "Продолжение таблицы 3\nМомент затяжки 200 Н·м"),
    ]


@pytest.fixture
def fake_index() -> Iterator[None]:
    pages.bind(FakeIndex())
    search._indexes.clear()
    yield
    pages.bind(None)
    search._indexes.clear()


def handles(doc_id: str, page: int) -> str:
    return f"S{page}"


def test_open_end_brings_next_page(fake_index: None) -> None:
    res = read.read_pages(ENGINE, handles, DOC.doc_id, [10])
    assert [p["pdf_page"] for p in res["pages"]] == [10, 11]  # стр. 10 кончается двоеточием
    assert res["added"][0]["pdf_page"] == 11 and "двоеточием" in res["note"]
    assert res["pages"][0]["text"].startswith(f"[S10] {DOC.designation}, стр. 10\nРаздел: Смазка")


def test_continued_table_brings_previous_page(fake_index: None) -> None:
    res = read.read_pages(ENGINE, handles, DOC.designation, ["21"])
    assert [p["pdf_page"] for p in res["pages"]] == [20, 21]


def test_other_engine_manual_and_missing_pages(fake_index: None) -> None:
    assert read.read_pages(ENGINE, handles, OTHER.doc_id, [10])["error"]  # руководство другого двигателя
    res = read.read_pages(ENGINE, handles, DOC.doc_id, [DOC.pages + 5])
    assert not res["pages"] and "Нет страниц" in res["error"]
    assert read.read_pages(ENGINE, handles, DOC.doc_id, [])["error"]


def test_tool_only_with_nikita(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEARCH_ENGINE", raising=False)
    assert "read_pages" not in {t.name for t in tools()}
    monkeypatch.setenv("SEARCH_ENGINE", "nikita")
    assert "read_pages" in {t.name for t in tools()}


def test_agent_reads_page_and_cites_it(
    fake_index: None, ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEARCH_ENGINE", "nikita")
    steps = [call("read_pages", manual=DOC.doc_id, pages=[10]), say("Давление масла 4,0 кгс/см2 [R1].")]
    ag, llm = make_agent(steps, ml, toir, prefetch=False)
    reply = ag.ask(ag.start(*ANOMALY), "Какое давление масла?")
    tool_msgs: list[dict[str, Any]] = [
        json.loads(str(m["content"])) for m in llm.seen[-1] if m["role"] == "tool" and m.get("name") == "read_pages"
    ]
    assert tool_msgs and [p["source"] for p in tool_msgs[0]["pages"]] == ["R1", "R2"]
    assert "4,0" in reply.text  # цифра со страницы проходит проверку
    assert {(s["manual"], int(s["pdf_page"])) for s in reply.sources} == {(DOC.designation, 10)}
