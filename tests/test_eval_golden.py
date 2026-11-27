"""Проверки раннера контрольных вопросов (`scripts/eval_golden.py`) без сервиса и модели: наборы целы, оценка кодом
ловит то, что должна, и не ловит лишнего."""

from __future__ import annotations

import json
import re

import pytest

from eval_golden import SETS, discipline, failure_class, grade, has_number, refusal_kind, session_for
from service.fleet import fleet
from service.manuals.catalog import DOCS_BY_ID, documents_for_engine


def questions(name: str) -> list[dict]:
    return [json.loads(ln) for ln in SETS[name].read_text(encoding="utf-8").splitlines() if ln.strip()]


@pytest.mark.parametrize(("name", "count"), [("golden", 36), ("heldout", 48)])
def test_sets_are_whole(name: str, count: int) -> None:
    qs = questions(name)
    assert len(qs) == count
    assert len({q["id"] for q in qs}) == count
    for q in qs:
        v = fleet().vehicle(q["vehicle_id"])
        assert v is not None, q["id"]
        session_for(q, v)  # у машины есть проверка, на которой задать вопрос
        own = {d.doc_id for d in documents_for_engine(v.engine_model)}
        for alt in q["accept"]:
            for doc, page in alt["pages"]:
                assert doc in own, f"{q['id']}: {doc} — не руководство {v.engine_model}"
                assert 1 <= page <= DOCS_BY_ID[doc].pages, f"{q['id']}: стр. {page} вне {doc}"
        for p in q["must_not_match"]:
            re.compile(p)
        assert q["must_refuse"] or q["accept"] or q["any_of"] or q["must_not_match"] or q.get("no_ticket"), q["id"]


def test_sets_carry_no_long_quotes() -> None:
    """В наборах — вопросы, числа и страницы; цитата руководства в заметке — не длиннее 24 слов."""
    for name in SETS:
        for q in questions(name):
            for quote in re.findall(r"«([^»]*)»", q["note"]):
                assert len(quote.split()) < 24, q["id"]


def test_numbers_match_whole() -> None:
    assert has_number("момент 135±15 Н·м", "15")
    assert not has_number("момент 1135 Н·м", "135")
    assert has_number("диаметр 130.02 мм", "130,02")
    assert not has_number("1107,95", "107,9")


def test_refusal_and_bans() -> None:
    assert refusal_kind("В руководстве не нашёл зазора свечей.", set()) == "wording"
    assert refusal_kind("У ЗМЗ-5234.10 нет турбокомпрессора.", {("zmz-5234-rk", 8)}) == "wording"
    assert refusal_kind("Давление 380 кПа [S1].", {("zmz-409-rk", 72)}) is None
    assert discipline("До дефектовки машину не эксплуатировать.") == {"ban_sourced": False}
    assert discipline("Эксплуатация не допускается [S2].") == {"ban_sourced": True}
    assert discipline("Повторите проверку: заглушите двигатель, закрепите датчик.") == {}
    assert discipline("Причину покажет дефектовка (мнение помощника, не из руководства).") == {"opinion_clean": True}
    assert discipline("Зазор 0,3 мм (мнение помощника, не из руководства).") == {"opinion_clean": False}


def test_grade_and_class() -> None:
    accept = [{"numbers": ["0,20", "0,30"], "pages": [["zmz-5234-rk", 21]]}]
    q = {"id": "t", "kind": "norm", "question": "?", "must_refuse": False, "any_of": [], "must_not_match": [],
         "all_alternatives": False, "accept": accept}  # fmt: skip
    own = {"zmz-5234-rk"}
    r = {"answer": "Зазор 0,20–0,30 мм [S1].", "cited": [["zmz-5234-rk", 21]], "events": [], "withdrawn": 0,
         "tickets_sent": 0, "verdict_text": ""}  # fmt: skip
    r["checks"] = grade(q, r, own)
    assert all(r["checks"].values())
    r = {**r, "answer": "В руководстве не нашёл зазора.", "cited": []}
    r["checks"] = grade(q, r, own)
    assert failure_class(q, r) == "отказ, где ответ есть"
    r = {**r, "answer": "Зазор 0,20–0,30 мм [S1].", "cited": [["zmz-409-rk", 43]]}
    r["checks"] = grade(q, r, own)
    assert failure_class(q, r) == "чужой двигатель"
