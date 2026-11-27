"""Страница продолжается на соседней (стабильные провалы открытой половины, 27.11): признаки, выдача, обрывки фраз,
ответ по найденному, когда шаги кончились."""

from __future__ import annotations

import json
from typing import Any

from service import page_links
from service.agent import MAX_STEPS, Agent, _edge
from service.clients import MLClient, ToirClient
from service.manual_search import ManualHit
from test_agent import ANOMALY, call, make_agent, say

STEPS_33 = "5. Проверить зазоры.\n6. Отрегулировать винтом.\n33\nРис. 18. Отвертывание контргайки"
STEPS_34 = "34\n7. Для следующего цилиндра провернуть вал.\nПорядок работы цилиндров: 1 – 4 – 2 – 5 – 3 – 6"


def test_signs_of_continuation() -> None:
    assert page_links.continues(STEPS_33, STEPS_34)  # пункт 7 после пункта 6
    assert page_links.continues("Таблица 3\nСтук 11.1", "214\nПродолжение таблицы 3\n11.2 Толкатель")
    head = "Причина неисправности Метод устранения"
    assert page_links.continues(f"56\n{head}\nИзнос вкладышей", f"57\n{head}\nЗадир стержня клапана")
    assert page_links.continues("…согласно перечислениям а) и б) в", "255 9\nпорядке работы цилиндров:")
    assert page_links.continues("Перед установкой проверить:", "Новая глава")
    assert not page_links.continues("ПРИЛОЖЕНИЕ 4\n23 | Кольцо | 4", "230\nПРИЛОЖЕНИЕ 5\nТаблица 39")


def test_edge_takes_whole_lines() -> None:
    page = "первая строка\nвторая строка\nтретья строка"
    assert _edge(page, 30) == "первая строка\nвторая строка"
    assert _edge(page, 30, tail=True) == "вторая строка\nтретья строка"


PAGES = {33: STEPS_33, 34: STEPS_34, 35: "35\nТЕХНИЧЕСКОЕ ОБСЛУЖИВАНИЕ"}


class Pages:
    available = True

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        return [ManualHit("yamz-236-re", "РЭ", 33, "Клапаны", STEPS_33)]

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        return PAGES.get(pdf_page)


def test_next_page_comes_with_search(ml: MLClient, toir: ToirClient) -> None:
    """Порядок работ продолжается на стр. 34 — она в выдаче сама, её цифры проверяемы (Q03)."""
    ag, llm = make_agent([call("search_manual", query="порядок регулировки клапанов"),
                          say("Порядок: 1-4-2-5-3-6 [R2].")], ml, toir, Pages(), prefetch=False)  # fmt: skip
    reply = ag.ask(ag.start(*ANOMALY), "В каком порядке регулировать клапаны?")
    found = json.loads(str(next(m for m in llm.seen[-1] if m["role"] == "tool")["content"]))["found"]
    assert [f["context"] for f in found if f.get("context")] == ["продолжение стр. 33"]
    assert "1-4-2-5-3-6" in reply.text and {s["pdf_page"] for s in reply.sources} == {34}


def test_answer_when_steps_run_out(ml: MLClient, toir: ToirClient) -> None:
    """Модель всё ищет — после последнего шага ответ по найденному без инструментов, а не «Не успел…»."""
    steps: list[Any] = [call("search_manual", query=f"запрос {i}") for i in range(MAX_STEPS)]
    ag, llm = make_agent([*steps, say("По найденному: проверьте зазоры [R1].")], ml, toir, Pages(), prefetch=False)
    reply = ag.ask(ag.start(*ANOMALY), "Как регулировать клапаны?")
    assert "Не успел" not in reply.text and "проверьте зазоры" in reply.text
    assert "шаги поиска кончились" in str(llm.seen[-1][-1]["content"])


def test_abbreviation_does_not_leave_a_stub(ml: MLClient, toir: ToirClient) -> None:
    """«должен быть св. 0,3 мм» — одно предложение: число не из руководства снимает его целиком, без обрывка
    «должен быть св.» (отчёт приёмщика)."""
    ag, _ = make_agent([say("Зазор должен быть св. 0,7 мм. Поэтому проверьте щупом [R1].")], ml, toir,
                       Pages(), prefetch=False)  # fmt: skip
    conv = ag.start(*ANOMALY)
    text, *_ = ag.guard(conv, "Зазор должен быть св. 0,7 мм. Поэтому проверьте щупом.")
    assert "св." not in text and "Поэтому проверьте щупом." in text
    assert isinstance(ag, Agent)
