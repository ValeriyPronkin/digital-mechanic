"""Приёмка по ответам организаторов 27.11 — три случая, которые на стенде (main 2ce108f) ломались.

1. Коренные подшипники ЯМЗ-236 (пример самих организаторов): значения в Н·м совпадают, расходится только пересчёт;
   стр. 41 отсылает к «Сборка двигателя» — стр. 248 (5.2.9): не менее трёх приёмов, опоры 2-3-1-4; приложение
   430-470 названо со своей страницей; строка модели «в два приёма» (слабая формулировка стр. 41) заменена.
2. Противоречие объявлено («см. ниже»), а блока нет — обрывка нет, совета «уточните у производителя» нет.
3. Ответа в руководстве нет (шины): «нет данных», конкретный шаг; порядка работ без страницы, отсылки к
   производителю и «ты» нет."""

from __future__ import annotations

from typing import Any

from service.clients import MLClient, ToirClient
from service.manual_search import ManualHit
from test_agent import ANOMALY, EmptySearch, make_agent, say
from test_safe_rule import PAGES


class MainBearing:
    available = True

    def search(self, query: str, engine: str, k: int = 5) -> list[ManualHit]:
        return [ManualHit("yamz-236-rk", "РК", 41, "Сборка", PAGES[("yamz-236-rk", 41)])]

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        return PAGES.get((manual_id, pdf_page))


def _ask(ml: MLClient, toir: ToirClient, answer: str, question: str, search: Any) -> str:
    ag, _ = make_agent([say(answer)], ml, toir, search)
    return ag.ask(ag.start("B418HK98", "S-0007"), question).text


def test_main_bearing_caps_safe_rule_from_the_pages(ml: MLClient, toir: ToirClient) -> None:
    answer = "Затягивайте болты крышек моментом 421-461 Н·м в два приёма [R1].\n\n1. Смажьте резьбу."
    text = _ask(ml, toir, answer, "С каким моментом тянуть болты крышек коренных подшипников?", MainBearing())
    rule = next(ln for ln in text.split("\n") if ln.startswith("Безопасное правило:"))
    assert "стр. 41 отсылает к разделу «Сборка двигателя» — действует он (РК, стр. 248)" in rule
    assert "не менее, чем в три приема" in rule and "от 421 до 461 Нм" in rule
    assert "«вторая опора, третья, первая и четвертая опоры»" in rule
    assert "В Н·м это значение совпадает (РК, стр. 41, 56, 248); расходится только пересчёт" in rule
    assert "Приложение (РК, стр. 286) даёт 430-470" in rule
    assert "в два приёма" not in text  # строка модели по слабой формулировке стр. 41 заменена
    for page in (41, 56, 248, 286):  # каждое значение — со своей страницей
        assert f"стр. {page}" in text
    assert "уточните" not in text.lower() and "производител" not in text


def test_announced_contradiction_without_block_leaves_no_stub(ml: MLClient, toir: ToirClient) -> None:
    answer = (
        "Обороты холостого хода в руководствах указаны по-разному — противоречие, см. ниже.\n\n"
        "Противоречие в документации:\n- «минимальная 550-650» [R1]\n- «минимальная 540-560» [R2]\n\n"
        "Уточните у производителя двигателя."
    )
    text = _ask(ml, toir, answer, "Какая минимальная частота вращения холостого хода?", EmptySearch())
    assert "см. ниже" not in text and "Противоречие в документации" not in text
    assert "Уточните" not in text and "540" not in text


def test_no_data_answer_gives_a_step_not_an_order_of_works(ml: MLClient, toir: ToirClient) -> None:
    answer = (
        "В руководстве этого двигателя нет данных о давлении в шинах.\n\n"
        "1. Смотри табличку на стойке двери.\n2. Открой колпачок и проверь давление манометром.\n"
        "3. Запроси нормы у производителя автомобиля (МАЗ).\n4. При износе протектора — дефектовка шин."
    )
    ag, _ = make_agent([say(answer)], ml, toir, EmptySearch())
    text = ag.ask(ag.start(*ANOMALY), "Какое давление в шинах?").text
    assert text.startswith("В руководстве этого двигателя нет данных")
    assert "табличку" not in text and "манометр" not in text and "МАЗ" not in text and "производител" not in text
    assert "1. При износе протектора — дефектовка шин." in text  # конкретный шаг, нумерация подряд
    for thou in ("Смотри", "Открой", "проверь", "Запроси"):
        assert thou not in text
