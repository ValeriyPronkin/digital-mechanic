"""Числа «из контекста» (дата проверки, оценка, номер страницы, обозначения) не подтверждают число с единицей.

Дыра: guard пропускал любое число, совпавшее с днём, часом, минутой или годом проверки, оценкой или уверенностью,
номером любой найденной страницы или цифрами обозначения — «момент 20 Н·м» проходил, если проверка была в 20:00.
Теперь, как `Context` в app/verify.py Никиты: дата и время — только записанные датой или временем без единицы;
оценка — только как написана (уверенность в % — со знаком %); обозначения машины, проверок, двигателя, документов и
код неисправности — метки, а не числа; номер страницы — только «стр. N» той страницы, на которую ссылается фраза.
Число с единицей — только со страницы, на которую ссылается фраза."""

from __future__ import annotations

import pytest

from service.agent import Source
from service.clients import MLClient, ToirClient
from test_agent import make_agent

VEHICLE = ("E549YT198", "S-0011")  # проверки 03.10 13:30, 20.10 11:40, 10.11 15:40; оценки 0,17 / 0,86 / 0,16


def _conv(ml: MLClient, toir: ToirClient):  # type: ignore[no-untyped-def]
    ag, _ = make_agent([], ml, toir)
    conv = ag.start(*VEHICLE)
    for ref, page, text in (
        ("R1", 12, "Гайки шпилек крепления головки цилиндров затягивать в три приёма."),
        ("R2", 120, "Зазор между коромыслом и клапаном 0,25-0,30 мм."),
    ):
        conv.sources[ref] = Source(ref=ref, manual_id="yamz-236-rk", manual="РК", pdf_page=page, section="", text=text)
    return ag, conv


@pytest.fixture(autouse=True)
def _own_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GUARD_OWN_SOURCE", raising=False)


@pytest.mark.parametrize(
    "claim",
    [
        "Момент затяжки гаек головки 20 Н·м [R1].",  # 20 — год 2026 / день 20.10
        "Момент затяжки гаек головки 40 Н·м [R1].",  # 40 — минуты 11:40 и 15:40
        "Момент затяжки гаек головки 120 Н·м [R1].",  # 120 — номер страницы R2, а не число со страницы R1
        "Зазор впускных клапанов 0,17 мм [R1].",  # 0,17 — оценка проверки 03.10
        "Зазор впускных клапанов 0,86 мм [R1].",  # 0,86 — оценка текущей проверки
        "Затягивать моментом 84 Н·м [R1].",  # 84 — уверенность 84 %
        "Затягивать моментом 236 Н·м [R1].",  # 236 — из обозначения двигателя ЯМЗ-236М2
    ],
)
def test_context_number_never_confirms_a_number_with_a_unit(ml: MLClient, toir: ToirClient, claim: str) -> None:
    ag, conv = _conv(ml, toir)
    text, *_ = ag.guard(conv, f"Затягивать в три приёма [R1].\n{claim}")
    assert claim not in text and "в три приёма [R1]" in text


def test_legitimate_dates_scores_and_labels_still_pass(ml: MLClient, toir: ToirClient) -> None:
    ag, conv = _conv(ml, toir)
    answer = (
        "Проверка 20.10.2026 в 11:40 показала оценку 0,86 при уверенности 84%.\n"
        "Прошлые проверки 03.10 и 10.11: оценки 0,17 и 0,16.\n"
        "Машина E549YT198 (Г-104), двигатель ЯМЗ-236М2, проверка S-0011, код F02.\n"
        "Зазор 0,25-0,30 мм [R2]."
    )
    text, *_ = ag.guard(conv, answer)
    assert text.startswith(answer.split("\n\n")[0]), text
    assert conv.passport["guard"]["numbers_dropped"] == 0 and conv.passport["guard"]["own_source_dropped"] == 0


def test_date_with_a_unit_is_a_size_not_a_date(ml: MLClient, toir: ToirClient) -> None:
    ag, conv = _conv(ml, toir)
    text, *_ = ag.guard(conv, "Зазор 20,10 мм [R2].")  # «20.10» — дата проверки, «20,10 мм» — размер
    assert "20,10" not in text


def test_page_label_counts_only_for_the_page_cited(ml: MLClient, toir: ToirClient) -> None:
    ag, conv = _conv(ml, toir)
    text, *_ = ag.guard(conv, "Зазор 0,25-0,30 мм, стр. 120 [R2].")
    assert "стр. 120 [R2]" in text  # метка той же страницы — не выдумка
    text, *_ = ag.guard(conv, "Порядок затяжки — стр. 120 [R1].")
    assert "стр. 120" not in text  # R1 — стр. 12: номер чужой страницы не подтверждён


def test_ticket_conclusion_number_needs_its_page(ml: MLClient, toir: ToirClient) -> None:
    ag, conv = _conv(ml, toir)
    ops = [{"text": "Подтянуть гайки", "ref": "R1"}]
    res = ag._draft_ticket(conv, {"conclusion": "Подтянуть гайки моментом 40 Н·м [R1].", "operations": ops})
    # заключение модели в заявку не идёт (#136): заключение пишет сервер, числа без страницы в нём нет
    assert "refused" not in res and "40" not in res["draft"]["conclusion"]


GENERATOR_57 = (
    "57\nНеисправность | Причина | Способ устранения\nПерегрев подшипников генератора | Чрезмерное натяжение ремня | "
    "Отрегулировать натяжение ремня"
)


def test_page_own_number_never_verifies(ml: MLClient, toir: ToirClient) -> None:
    """Стенд 27.11, A427MA78: ответ ссылался на РЭ стр. 57 (таблица неисправностей генератора), интерфейс ставил ✓
    «на странице найдено число из ответа» по колонтитулу «57». Номер страницы ничего не подтверждает."""
    from service import api_v2
    from service.agent import AgentReply

    ag, conv = _conv(ml, toir)
    conv.sources["R3"] = Source(ref="R3", manual_id="yamz-236-re", manual="РЭ", pdf_page=57, section="",
                                text=GENERATOR_57)  # fmt: skip
    text, *_ = ag.guard(conv, "Натяжение ремня генератора 57 Н [R3].")
    assert "57 Н" not in text  # колонтитул «57» — не значение со страницы
    answer = "Порядка работ по этому узлу в руководстве нет, норм по перегреву нет [R3]."
    reply = AgentReply(text=answer, grounded=True, notes=[], sources=[conv.sources["R3"].public()], draft=None,
                       trace={})  # fmt: skip
    ver = api_v2.verification(reply, answer)
    assert ver["verified"] == [] and ver["quotes"] == {}  # нет ✓ и нет «Найдено на странице: 57»


def test_abbreviation_does_not_end_a_sentence(ml: MLClient, toir: ToirClient) -> None:
    """Стенд 27.11: «… в последовательности по рис. 6 [S1].» — после «рис.» фраза резалась, «6 [R1]» снимался,
    и ответ терял ссылку и обрывался на «по рис.». То же — «у гаек поз.» из eval."""
    ag, conv = _conv(ml, toir)
    conv.sources["R4"] = Source(ref="R4", manual_id="yamz-236-rk", manual="РК", pdf_page=250, section="",
                                text="Гайки шпилек крепления головки цилиндров 240-260 Н·м (24-26 кгс·м), "
                                "порядок затяжки — рис. 6. Гайки поз. 5 — 40 Н·м.")  # fmt: skip
    answer = ("Гайки шпилек — 240–260 Н·м (24–26 кгс·м) в последовательности по рис. 6 [R4].\n"
              "Момент у гаек поз. 5 — 40 Н·м [R4].")  # fmt: skip
    text, *_ = ag.guard(conv, answer)
    assert "по рис. 6 [R4]." in text and "у гаек поз. 5 — 40 Н·м [R4]." in text


def test_part_designations_of_the_shown_draft_are_labels(ml: MLClient, toir: ToirClient) -> None:
    """Видео-машина B418HK98 (27.11): после черновика «В заявку включены втулка коромысла (236-1007118)…» снималось —
    обозначения деталей черновика код уже сверил со страницами. Чужое обозначение по-прежнему требует страницы."""
    ag, conv = _conv(ml, toir)
    conv.sources["R5"] = Source(ref="R5", manual_id="yamz-236-re", manual="РЭ", pdf_page=169, section="",
                                text="Втулка коромысла 236-1007118-В 12 0,03 0,36")  # fmt: skip
    args = {
        "conclusion": "Дефектовка клапанного механизма [R5].",
        "operations": [{"text": "Втулка коромысла", "ref": "R5"}],
        "spare_parts": [{"text": "Втулка коромысла 236-1007118-В", "ref": "R5"}],
    }
    res = ag._draft_ticket(conv, args)
    assert "draft" in res, res
    parts = " ".join(conv.draft.body.spare_parts)
    assert "236-1007118" in parts
    text, *_ = ag.guard(conv, "В заявку включена втулка коромысла (236-1007118).")
    assert "236-1007118" in text
    text, *_ = ag.guard(conv, "В заявку включена втулка (236-1007999).")
    assert "236-1007999" not in text


def test_figure_table_and_item_numbers_are_references(ml: MLClient, toir: ToirClient) -> None:
    """Eval 27.11 (ЗМЗ-5234, датчик температуры): «собрать схему по рис. 48 [S1]» снималось — номер рисунка не величина.
    Величина рядом по-прежнему проверяется."""
    ag, conv = _conv(ml, toir)
    text, *_ = ag.guard(conv, "Собрать схему по рис. 48, табл. 10, п. 5.2.9 [R1].")
    assert "рис. 48, табл. 10, п. 5.2.9 [R1]" in text
    text, *_ = ag.guard(conv, "Собрать схему по рис. 48 с сопротивлением 100 Ом [R1].")
    assert "100 Ом" not in text  # 100 Ом на странице R1 нет


def test_engine_variant_and_position_lists_are_labels(ml: MLClient, toir: ToirClient) -> None:
    """Eval 27.11: «ЯМЗ-53642-20: 1130 Н·м» снималось за «42» и «20» из обозначения, «гайки поз. 11 и 12 — 24,5…29,4 Н·м»
    — за номер позиции «12». Величина после перечня («по рис. 5 и 20 Н·м») по-прежнему проверяется."""
    ag, conv = _conv(ml, toir)
    conv.sources["R5"] = Source(ref="R5", manual_id="yamz-236-rk", manual="РК", pdf_page=130, section="",
                                text="Максимальный крутящий момент 1130 (115). Гайки 24,5…29,4 Н·м")  # fmt: skip
    answer = "ЯМЗ-53642-20: 1130 Н·м (115 кгс·м) [R5].\nГайки поз. 11 и 12 — 24,5…29,4 Н·м [R5]."
    text, *_ = ag.guard(conv, answer)
    assert "ЯМЗ-53642-20: 1130 Н·м" in text and "поз. 11 и 12 — 24,5…29,4 Н·м" in text
    text, *_ = ag.guard(conv, "Затянуть по рис. 5 и 20 Н·м [R5].")
    assert "20 Н·м" not in text
