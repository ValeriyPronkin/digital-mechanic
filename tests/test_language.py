"""Язык ответа (задача Валерия 27.11): определение кодом, указание модели, перевод ответа не на том языке, голос."""

from __future__ import annotations

import pytest

from service import language
from service.agent import Source
from service.clients import MLClient, ToirClient
from service.voice import speech_for, speech_lang, spoken_text, voice_and_lang
from test_agent import ANOMALY, make_agent, say


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Bu dvigatelda klapanlarning issiqlik tirqishi qancha bo'lishi kerak?", "uz"),
        ("Forsunkani yechyapman — oʻrnatishda nimani almashtirish kerak?", "uz"),
        ("Бу двигателда клапанларнинг иссиқлик тирқиши қанча бўлиши керак?", "uz-cyrl"),
        ("Болтҳои сарпӯши подшипникҳои асосии вали тирсакӣ бо кадом момент кашида мешаванд?", "tg"),
        ("Негізгі мойынтіректер қақпағының бұрандамаларын қандай моментпен тарту керек?", "kk"),
        ("Клапандардын жылуулук боштугу канча болушу керек?", "ky"),
        ("Какой момент затяжки крышек коренных подшипников?", "ru"),
        ("слушай брат момент затяжка коренной крышка какой нада", "ru"),  # ломаный русский — ответ по-русски
        ("What is the valve clearance of this engine?", "en"),
    ],
)
def test_detect(text: str, code: str) -> None:
    assert language.detect(text) == code


def test_normalize() -> None:
    assert language.normalize("tj") == "tg" and language.normalize("uz-UZ") == "uz"
    assert language.normalize("auto") is None and language.normalize(None) is None


def test_matches() -> None:
    assert not language.matches("Зазор впускных клапанов 0,30–0,40 мм [R1].", "uz")
    assert language.matches("Kirish klapanlari tirqishi 0,30–0,40 мм [R1].", "uz")
    tg = "Момент: 98…107,9 Н·м [R1]. Дар дастур: «Болты крепления крышек коренных подшипников» (болтҳои сарпӯш)."
    assert language.matches(tg, "tg")
    assert not language.matches("Момент затяжки 98…107,9 Н·м [R1]. Затягивайте равномерно.", "tg")
    assert language.matches("Любой ответ", "ru")


def test_uz_to_latin() -> None:
    assert language.uz_to_latin("Ўзбекча ёғ қанча") == "Oʻzbekcha yogʻ qancha"
    assert language.uz_to_latin("Ер ва сув") == "Yer va suv"


def test_answer_in_wrong_language_is_translated(ml: MLClient, toir: ToirClient) -> None:
    ag, llm = make_agent(
        [say("Проверьте давление масла манометром."), say("Moy bosimini manometr bilan tekshiring.")],
        ml, toir, prefetch=False,
    )  # fmt: skip
    reply = ag.ask(ag.start(*ANOMALY), "Moy bosimini qanday tekshirish kerak? Bu dvigatel uchun nima qilish kerak?")
    assert reply.lang == "uz" and reply.text.startswith("Moy bosimini")
    assert "узбекский" in str(llm.seen[0][-1]["content"])  # указание — рядом с вопросом
    assert any("перевод ответа" in s["name"] for s in reply.trace["steps"] if s["kind"] == "llm")


def test_answer_in_right_language_costs_nothing_extra(ml: MLClient, toir: ToirClient) -> None:
    ag, llm = make_agent([say("Moy bosimini manometr bilan tekshiring.")], ml, toir, prefetch=False)
    reply = ag.ask(ag.start(*ANOMALY), "Moy bosimini qanday tekshirish kerak? Bu dvigatel uchun nima qilish kerak?")
    assert reply.lang == "uz" and len(llm.seen) == 1


def test_mechanic_chooses_russian(ml: MLClient, toir: ToirClient) -> None:
    ag, llm = make_agent([say("Проверьте давление масла манометром.")], ml, toir, prefetch=False)
    reply = ag.ask(ag.start(*ANOMALY), "Moy bosimini qanday tekshirish kerak? Bu dvigatel uchun nima qilish kerak?",
                   lang="ru")  # fmt: skip
    assert reply.lang == "ru" and len(llm.seen) == 1 and "Язык ответа" not in str(llm.seen[0][-1]["content"])


def _src() -> dict[str, Source]:
    return {"R1": Source(ref="R1", manual_id="m", manual="ЯМЗ-536. Руководство по эксплуатации", pdf_page=173,
                         section="", text="впускных клапанов: 0,30 – 0,40 мм")}  # fmt: skip


def test_speech_in_answer_language() -> None:
    sp = speech_for("Kirish klapanlari tirqishi 0,30–0,40 mm [R1].", _src(), "uz")
    assert "Manba:" in sp.text and "173-sahifa" in sp.text
    tg = speech_for("Тирқиши 0,30–0,40 мм [R1].", _src(), "tg")
    assert tg.text.startswith("Озвучки на языке «таджикский» нет") and not tg.refs


def test_voice_by_language() -> None:
    assert voice_and_lang("kk", "zahar") == ("amira", "kk-KZ")
    assert voice_and_lang("uz-cyrl", "zahar") == ("nigora", "uz-UZ")
    assert voice_and_lang("tg", "zahar") == ("zahar", "ru-RU")
    assert speech_lang("tg") == "ru" and speech_lang("uz") == "uz"
    assert spoken_text("Тирқиш 0,30 мм", "uz-cyrl") == "Tirqish 0,30 mm"
    assert "миллиметра" in spoken_text("0,30 мм", "ru")
