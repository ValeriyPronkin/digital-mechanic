"""Качество ответов (issue #28): окно страницы, план поиска (перевод, слова руководства), несколько запросов."""

from __future__ import annotations

import json
from typing import Any

import httpx

from service.agent import _page_window
from service.clients import MLClient, ToirClient
from service.llm import DeepSeekProvider, LLMReply
from service.manual_search import ManualHit
from test_agent import ANOMALY, NORMAL, ScriptedLLM, make_agent, say

PAGE = (
    "Регулировка зазоров в клапанном механизме.\n"
    + "\n".join(f"Пункт {i}. Общий текст про порядок работ без цифр." for i in range(1, 40))
    + "\nВеличина зазора на холодном двигателе 0,20…0,30 мм.\n"
    + "Примечание: болты маховика повторно использовать не более трех раз."
)


class PageSearch:
    """Поиск-фикстура: фрагмент без цифр, а значение — дальше на той же странице; запоминает запросы."""

    available = True

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        self.queries.append(query)
        text = "Регулировка зазоров в клапанном механизме."
        hit = ManualHit("zmz-5234-rk", "Руководство по ремонту", 20, "ГРМ", text)
        return [hit]

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        return PAGE if (manual_id, pdf_page) == ("zmz-5234-rk", 20) else None


def test_page_window_reaches_value_in_neighbouring_fragment() -> None:
    from service.manuals.lexical import tokenize

    w = _page_window(PAGE, "Регулировка зазоров в клапанном механизме.", tokenize("зазор клапанов холодный"), 600)
    assert "0,20…0,30" in w and len(w) <= 600


def test_model_sees_window_and_number_passes_check(ml: MLClient, toir: ToirClient) -> None:
    search = PageSearch()
    ag, llm = make_agent([say("Зазор 0,20…0,30 мм на холодном двигателе [R1].")], ml, toir, search)
    reply = ag.ask(ag.start(*ANOMALY), "Какой зазор клапанов?")
    tool = next(m for m in llm.seen[0] if m["role"] == "tool" and m.get("name") == "search_manual")
    assert "0,20…0,30" in json.loads(str(tool["content"]))["found"][0]["text"]
    assert "0,20…0,30" in reply.text and not any("убрал" in n for n in reply.notes)


def _plan(content: str) -> LLMReply:
    return LLMReply(content)


def test_search_plan_translates_and_rewrites(ml: MLClient, toir: ToirClient) -> None:
    plan = {"lang": "uz", "question_ru": "Какой тепловой зазор клапанов?",
            "queries": ["регулировка тепловых зазоров клапанов", "зазор впускных и выпускных клапанов"]}  # fmt: skip
    search = PageSearch()
    ag, llm = make_agent([_plan(json.dumps(plan, ensure_ascii=False)), say("Javob [R1].")], ml, toir, search,
                         plan_search=True)  # fmt: skip
    reply = ag.ask(ag.start(*ANOMALY), "Klapanlarning issiqlik tirqishi qancha?")
    assert search.queries[0] == "Какой тепловой зазор клапанов?"
    assert "регулировка тепловых зазоров клапанов" in search.queries
    tool = next(m for m in llm.seen[1] if m["role"] == "tool" and m.get("name") == "search_manual")
    assert json.loads(str(tool["content"]))["answer_language"].startswith("uz")
    plan_steps = [s for s in reply.trace["steps"] if s["kind"] == "llm" and "план поиска" in s["name"]]
    assert len(plan_steps) == 1 and plan_steps[0]["cost_rub"] > 0  # план — в стоимости запроса


def test_broken_plan_falls_back_to_question(ml: MLClient, toir: ToirClient) -> None:
    search = PageSearch()
    ag, _ = make_agent([_plan("не JSON"), say("ок")], ml, toir, search, plan_search=True)
    ag.ask(ag.start(*NORMAL), "Какой зазор клапанов?")
    assert search.queries == ["Какой зазор клапанов?"]


def test_plan_gets_masked_question(ml: MLClient, toir: ToirClient) -> None:
    ag, llm = make_agent([_plan("{}"), say("ок")], ml, toir, PageSearch(), plan_search=True)
    ag.ask(ag.start(*ANOMALY), "Механик Иванов Иван Иванович, тел. +7 912 345-67-89: какой зазор?")
    sent = json.dumps(llm.seen[0], ensure_ascii=False, default=str)
    assert "Иванов" not in sent and "912 345" not in sent


def test_several_queries_merge_without_repeats(ml: MLClient, toir: ToirClient) -> None:
    class Two:
        available = True

        def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
            pages = {"а": [1, 2, 3], "б": [2, 4, 5]}[query]
            return [ManualHit("zmz-5234-rk", "РК", p, "", f"текст {p}") for p in pages]

    ag, _ = make_agent([say("ок")], ml, toir, Two())
    merged = ag._search_many(["а", "б"], "ЗМЗ-5234.10", 4)
    assert [h.pdf_page for h in merged] == [1, 2, 4, 3]  # по очереди лучшие из каждого, без повтора стр. 2


def test_deepseek_without_tools_sends_no_tools_key() -> None:
    sent: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        sent.update(json.loads(req.content))
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "{}"}}], "usage": {}})

    p = DeepSeekProvider("k", http=httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler)))
    p.chat([{"role": "user", "content": "?"}], [])
    assert "tools" not in sent
    assert isinstance(ScriptedLLM, type)


OPINION = "(мнение помощника, не из руководства)"


def _guarded(ml: MLClient, toir: ToirClient, text: str) -> str:
    ag, _ = make_agent([say(text)], ml, toir, PageSearch())
    return ag.ask(ag.start(*ANOMALY), "Как проверить натяжение ремня?").text


def test_unsourced_diagnosis_is_marked(ml: MLClient, toir: ToirClient) -> None:
    """Проверка с телефона: «Ремень здесь ни при чём: цокот в головках — это клапанный узел» — рассуждение модели."""
    answer = "Прогиб ремня 0,20…0,30 мм [R1].\nРемень здесь ни при чём: цокот в головках — это клапанный узел."
    text = _guarded(ml, toir, answer)
    assert "Прогиб ремня 0,20…0,30 мм [R1]." in text  # со ссылкой — как есть
    assert f"это клапанный узел. {OPINION}" in text


def test_sourced_cause_is_kept_as_is(ml: MLClient, toir: ToirClient) -> None:
    text = _guarded(ml, toir, "Причина стука — увеличенный зазор в клапанном механизме [R1].")
    assert OPINION not in text


def test_unsourced_cause_in_list_is_marked(ml: MLClient, toir: ToirClient) -> None:
    text = _guarded(ml, toir, "Нажать на ветвь с усилием 40 Н [R1].\n- Скорее всего, ремень вытянулся.")
    assert f"вытянулся. {OPINION}" in text


def test_plain_steps_without_diagnosis_are_not_marked(ml: MLClient, toir: ToirClient) -> None:
    text = _guarded(ml, toir, "Снимите крышку головки [R1].\nСкажите, если нужен черновик заявки.")
    assert OPINION not in text


def test_no_link_card_line_is_dropped(ml: MLClient, toir: ToirClient) -> None:
    """Связь с карточкой — только если она есть: строка «к этому не относится» из ответа убирается кодом."""
    for line in (
        "По карточке: отклонение по клапанному механизму — связь с натяжением ремней руководство не указывает.",
        "По карточке проверки — признак по клапанному механизму, к натяжению ремней руководство это прямо не относит.",
        "Карточка — отдельная тема, к ремню не относится.",
    ):
        text = _guarded(ml, toir, f"Нажать на ветвь с усилием 40 Н [R1].\n\n{line}")
        assert "карточ" not in text.lower() and text.startswith("Нажать")


def test_card_line_with_source_is_kept(ml: MLClient, toir: ToirClient) -> None:
    answer = "Нажать на ветвь с усилием 40 Н [R1].\nПо карточке: ослабший ремень даёт стук — см. [R1]."
    text = _guarded(ml, toir, answer)
    assert "По карточке" in text
