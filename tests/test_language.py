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
        ("मुख्य बेयरिंग कैप के बोल्ट किस टॉर्क से कसने हैं?", "hi"),
        ("Bhai, main bearing cap ke nut ka tightening torque kitna hai?", "hi"),  # хинглиш
        ("What is the main bearing cap torque?", "en"),
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


def test_answer_in_right_language_is_not_translated(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Moy bosimini manometr bilan tekshiring."), say("Проверьте давление масла манометром.")],
                         ml, toir, prefetch=False)  # fmt: skip
    reply = ag.ask(ag.start(*ANOMALY), "Moy bosimini qanday tekshirish kerak? Bu dvigatel uchun nima qilish kerak?")
    assert reply.lang == "uz" and reply.text.startswith("Moy bosimini")  # второй вызов — только «по-русски»
    assert not any("перевод ответа" in s["name"] for s in reply.trace["steps"] if s["kind"] == "llm")


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


HI = "तेल का दबाव कैसे जाँचें? इस इंजन के लिए क्या करना चाहिए?"


def test_hindi_back_translation_from_russian_original(ml: MLClient, toir: ToirClient) -> None:
    """Модель ответила по-русски — перевод на хинди, а «по-русски» — исходный ответ, без третьего вызова."""
    ag, llm = make_agent([say("Проверьте давление масла манометром."), say("मैनोमीटर से तेल का दबाव जाँचें।")],
                         ml, toir, prefetch=False)  # fmt: skip
    reply = ag.ask(ag.start(*ANOMALY), HI)
    assert reply.lang == "hi" and reply.text.startswith("मैनोमीटर")
    assert reply.back_translation == "Проверьте давление масла манометром." and len(llm.seen) == 2


def test_hindi_back_translation_numbers_checked(ml: MLClient, toir: ToirClient) -> None:
    """Ответ сразу на хинди — один вызов перевода на русский; цифра не из руководства в нём убирается guard."""
    ag, llm = make_agent([say("मैनोमीटर से तेल का दबाव जाँचें।"),
                          say("Проверьте давление масла манометром. Давление должно быть 777 кПа.")],
                         ml, toir, prefetch=False)  # fmt: skip
    reply = ag.ask(ag.start(*ANOMALY), HI)
    assert reply.back_translation is not None and "манометром" in reply.back_translation
    assert "777" not in reply.back_translation and len(llm.seen) == 2
    assert any("по-русски для проверки" in s["name"] for s in reply.trace["steps"] if s["kind"] == "llm")


def test_russian_answer_has_no_back_translation(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Проверьте давление масла манометром.")], ml, toir, prefetch=False)
    assert ag.ask(ag.start(*ANOMALY), "Как проверить давление масла?").back_translation is None


def test_hindi_no_voice() -> None:
    sp = speech_for("दबाव 0,30 мм [R1].", _src(), "hi")
    assert sp.text.startswith("Озвучки на языке «хинди» нет")


# ---------- таджикский против узбекской кириллицы (приёмщик 27.11: ответ пришёл узбекской кириллицей) ----------

TG_SHARED = [  # только общие буквы ҳ қ ғ, без ӣ ӯ ҷ — решают слова
    "Моменти кашидани болтҳои сарпушҳои подшипникҳои асосии ин муҳаррик чанд аст?",
    "Гайкаҳои сарпушҳои подшипникҳои асосиро бо кадом момент тоб медиҳанд?",
    "Мошинро бо қувваи худаш то база бурдан мумкин аст ё не?",
    "Тирқиши клапанҳоро чи тавр тафтиш ва танзим мекунанд — тирқиш чанд аст?",
]
UZ_CYRL = [
    "Двигателда мой босими қанча бўлиши керак?",
    "Қопқоқ болтлари учун тортиш моменти қанча?",
    "Бу машинани ҳайдаш мумкинми, двигател тақиллаяпти?",
    "Клапан тирқишини қандай текшириш керак?",  # без ў: узбекские слова
]


@pytest.mark.parametrize("text", TG_SHARED)
def test_tajik_with_shared_letters_only(text: str) -> None:
    assert not any(c in text for c in "ӣӯҷ")
    assert language.detect(text) == "tg"


@pytest.mark.parametrize("text", UZ_CYRL)
def test_uzbek_cyrillic_stays_uzbek(text: str) -> None:
    assert language.detect(text) == "uz-cyrl"


def test_tajik_letters_win_and_tajik_without_keyboard() -> None:
    assert language.detect("Ин мошинро ҳоло рондан мумкин аст? Чӣ кор кунам?") == "tg"  # ӣ — только таджикский
    assert language.detect("Хаст мухаррик барои ин мошин чи гуна кор мекунад?") == "tg"  # без особых букв — по словам


def test_tajik_answer_is_not_uzbek() -> None:
    assert language.matches("Моменти кашидан 98…107,9 Н·м аст [R1]. Болтҳоро бо ду қабул кашед.", "tg")
    assert not language.matches("Тортиш моменти 98…107,9 Н·м бўлиши керак [R1].", "tg")


def test_asked_language_and_actual_language() -> None:
    """Сессия 1, 27.11: «Скажи по-узбекски» — ответ на узбекском, а событие language было «Русский»."""
    assert language.requested("Скажи по-узбекски, какой зазор?") == "uz"
    assert language.requested("Ответь на казахском") == "kk"
    assert language.requested("Какой зазор клапанов?") is None
    assert language.actual("Klapan tirqishi 0,25–0,30 mm boʻlishi kerak [R1]. Sovuq dvigatelda sozlanadi.") == "uz"
    assert language.actual("Зазор 0,25–0,30 мм [R1].") == "ru"


def test_say_in_uzbek_sets_reply_language(ml: MLClient, toir: ToirClient) -> None:
    answer = "Klapan tirqishi 0,25–0,30 mm boʻlishi kerak [R1]. Sovuq dvigatelda sozlanadi."
    ag, _ = make_agent([say(answer)] * 3, ml, toir)
    reply = ag.ask(ag.start(*ANOMALY), "Скажи по-узбекски, какой зазор клапанов?")
    assert reply.lang == "uz"
