"""Качество ответов (issue #28): окно страницы, план поиска (перевод, слова руководства), несколько запросов."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from matrix_fixture import needs_matrix
from service.agent import _page_window
from service.clients import MLClient, ToirClient
from service.llm import DeepSeekProvider, LLMReply
from service.manual_search import ManualHit
from test_agent import ANOMALY, NORMAL, ScriptedLLM, make_agent, say

PAGE = (
    "Регулировка зазоров в клапанном механизме.\n"
    + "\n".join(f"Пункт {i}. Общий текст про порядок работ без цифр." for i in range(1, 40))
    + "\nВеличина зазора на холодном двигателе 0,20…0,30 мм.\n"
    + "Примечание: болты маховика повторно использовать не более трех раз.\n"
    # число, на которое ссылаются ответы-фикстуры «с усилием 40 Н [R1]»: раньше его пропускали минуты проверки 11:40
    + "Нажать на ветвь ремня с усилием 40 Н."
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


@pytest.mark.usefixtures("without_matrix")
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
    ag, llm = make_agent([_plan(json.dumps(plan, ensure_ascii=False)), say("Javob [R1]."), say("Ответ [R1].")],
                         ml, toir, search, plan_search=True)  # fmt: skip  # третий вызов — «по-русски»
    reply = ag.ask(ag.start(*ANOMALY), "Klapanlarning issiqlik tirqishi qancha?")
    assert search.queries[0] == "Какой тепловой зазор клапанов?"
    assert "регулировка тепловых зазоров клапанов" in search.queries
    tool = next(m for m in llm.seen[1] if m["role"] == "tool" and m.get("name") == "search_manual")
    assert "узбекский" in json.loads(str(tool["content"]))["answer_language"]
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


OPINION = "(предположение, не из руководства)"


def _guarded(ml: MLClient, toir: ToirClient, text: str) -> str:
    ag, _ = make_agent([say(text)], ml, toir, PageSearch())
    return ag.ask(ag.start(*ANOMALY), "Как проверить натяжение ремня?").text


@pytest.mark.usefixtures("without_matrix")
def test_unsourced_diagnosis_is_marked(ml: MLClient, toir: ToirClient) -> None:
    """Проверка с телефона: «Ремень здесь ни при чём: цокот в головках — это клапанный узел» — рассуждение модели."""
    answer = "Прогиб ремня 0,20…0,30 мм [R1].\nРемень здесь ни при чём: цокот в головках — это клапанный узел."
    text = _guarded(ml, toir, answer)
    assert "Прогиб ремня 0,20…0,30 мм [R1]." in text  # со ссылкой — как есть
    # мнение — только общий совет: деталь из рассуждения модели не остаётся (приёмка v2)
    assert "клапанный узел" not in text and f"дефектовка этого узла {OPINION}" in text


def test_sourced_cause_is_kept_as_is(ml: MLClient, toir: ToirClient) -> None:
    text = _guarded(ml, toir, "Причина стука — увеличенный зазор в клапанном механизме [R1].")
    assert OPINION not in text


def test_unsourced_cause_in_list_is_marked(ml: MLClient, toir: ToirClient) -> None:
    text = _guarded(ml, toir, "Нажать на ветвь с усилием 40 Н [R1].\n- Скорее всего, ремень вытянулся.")
    assert "вытянулся" not in text and f"дефектовка этого узла {OPINION}" in text


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


# ---------- связь с карточкой — кодом по матрице (проверка с телефона, B418HK98 / F01) ----------

BELT = ("yamz-236-re", 28, "Прогиб ремня водяного насоса 7–12 мм при усилии 40 Н.")
VALVE = ("yamz-236-re", 31, "Тепловой зазор клапанов 0,25-0,30 мм на холодном двигателе.")


class OnePage:
    available = True

    def __init__(self, page: tuple[str, int, str]) -> None:
        self.page = page

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        doc, num, text = self.page
        return [ManualHit(doc, "ЯМЗ-236М2, ЯМЗ-238М2. Руководство по эксплуатации 236-3902150-Б РЭ", num, "", text)]


def _cite(answer: str) -> Any:
    """Ответ-сценарий ссылается на страницу из поиска: R1… могут быть заняты страницами матрицы карточки."""

    def step(messages: list[Any]) -> LLMReply:
        tool = next(m for m in reversed(messages) if m.get("role") == "tool" and m.get("name") == "search_manual")
        ref = json.loads(str(tool["content"]))["found"][0]["ref"]
        return LLMReply(answer.replace("[R1]", f"[{ref}]"))

    return step


def _ask_b418(ml: MLClient, toir: ToirClient, page: tuple[str, int, str], answer: str, question: str) -> Any:
    ag, _ = make_agent([_cite(answer)], ml, toir, OnePage(page))
    return ag.ask(ag.start("B418HK98", "S-0008"), question)


@needs_matrix
def test_unrelated_question_gets_matrix_link_line_and_button(ml: MLClient, toir: ToirClient) -> None:
    from service.fault_matrix import cell_for

    reply = _ask_b418(ml, toir, BELT, "Прогиб 7–12 мм при усилии 40 Н [R1].", "Как проверить натяжение ремня")
    last = reply.text.strip().splitlines()[-1]
    assert last.startswith("К найденной неисправности это не относится. По руководству при «Клапанный механизм»")
    cell = cell_for("F01", "ЯМЗ-236М2")
    assert cell is not None and str(cell.operations[0].page) in last  # работы и страницы — из ячейки матрицы
    assert "предположение, не из руководства" not in last  # строка кода, не рассуждение модели
    assert reply.followup == {
        "label": "Проверка по «Клапанный механизм»",
        "question": "Что проверить по неисправности F01 «Клапанный механизм»?",
    }


def test_related_question_has_no_link_line(ml: MLClient, toir: ToirClient) -> None:
    reply = _ask_b418(ml, toir, VALVE, "Зазор 0,25-0,30 мм [R1].", "Какой зазор клапанов?")
    assert "К найденной неисправности" not in reply.text and reply.followup is None


def test_card_question_has_no_link_line(ml: MLClient, toir: ToirClient) -> None:
    reply = _ask_b418(ml, toir, BELT, "Прогиб 7–12 мм [R1].", "Что с двигателем, что делать?")
    assert "К найденной неисправности" not in reply.text and reply.followup is None


@needs_matrix
def test_link_line_survives_answer_cache(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([_cite("Прогиб 7–12 мм при усилии 40 Н [R1].")], ml, toir, OnePage(BELT))
    ag.ask(ag.start("B418HK98", "S-0008"), "Как проверить натяжение ремня")
    hit = ag.ask(ag.start("B418HK98", "S-0008"), "Как проверить натяжение ремня")
    assert hit.trace.get("cache") and hit.followup is not None
    assert hit.text.count("К найденной неисправности") == 1


@needs_matrix
def test_model_no_link_sentence_inside_sourced_line_is_dropped(ml: MLClient, toir: ToirClient) -> None:
    answer = (
        "Прогиб 7–12 мм при усилии 40 Н [R1]. По карточке проверки — неисправность клапанного механизма, "
        "к натяжению ремней руководство её не относит."
    )
    reply = _ask_b418(ml, toir, BELT, answer, "Как проверить натяжение ремня")
    assert "руководство её не относит" not in reply.text and "Прогиб 7–12 мм" in reply.text
    assert reply.text.count("К найденной неисправности") == 1


@needs_matrix
def test_any_unsourced_card_sentence_is_replaced_by_code_line(ml: MLClient, toir: ToirClient) -> None:
    answer = "Прогиб 7–12 мм [R1].\n\nПо карточке: отклонение по клапанному механизму, к ремням связи не даёт."
    reply = _ask_b418(ml, toir, BELT, answer, "Как проверить натяжение ремня")
    assert "связи не даёт" not in reply.text and reply.text.count("К найденной неисправности") == 1


def test_opinion_with_work_part_or_number_is_cut(ml: MLClient, toir: ToirClient) -> None:
    """Приёмка v2: под пометкой «мнение» — советы по деталям и цифры. Остаётся один общий совет."""
    answer = ("Нажать на ветвь с усилием 40 Н [R1].\n"
              "1. Скорее всего, люфт ротора турбины больше 0,5 мм — снимите патрубок и проверьте рукой.\n"
              "2. Вероятно, изношен натяжитель — замените его.")  # fmt: skip
    text = _guarded(ml, toir, answer)
    assert "люфт ротора" not in text and "натяжитель" not in text and "0,5" not in text
    assert text.count(OPINION) == 1 and "усилием 40 Н [R1]" in text


def test_generic_opinion_advice_is_kept(ml: MLClient, toir: ToirClient) -> None:
    text = _guarded(ml, toir, "Нажать на ветвь [R1].\nСкорее всего, нужна дефектовка натяжителя.")
    assert "нужна дефектовка натяжителя" in text
    text = _guarded(ml, toir, "Нажать на ветвь [R1].\nСкорее всего, лучше обратиться к специалисту.")
    assert "специалист" not in text  # механик сам специалист (правило заказчика 27.11)
