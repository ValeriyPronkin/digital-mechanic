"""Язык ответа (задача Валерия 27.11): механики — в т. ч. из Узбекистана, Таджикистана, Казахстана, Киргизии.

Язык вопроса определяет код (буквы и частые слова), а не модель: указание «ответь на …» стоит рядом с вопросом,
а не в результате поиска, где модель его пропускала. Механик может выбрать язык сам (`lang` в /api/v2/chat).
Поиск по руководству — как раньше, через перевод вопроса на русский; цифры, единицы, обозначения и [R…] — как
в руководстве, поэтому проверка цифр (guard) работает и для перевода. Ответ не на том языке — один вызов
перевода (`Agent._fix_language`), его цифры снова проверяет guard.

Голос (SpeechKit, документация aistudio.yandex.ru/docs/ru/speechkit, 27.11): распознавание — ru-RU, uz-UZ
(латиница), kk-KZ, en-US; синтез — ru, uz (nigora), kk (amira), en (john). Таджикского и киргизского нет ни там,
ни там: голосом — по-русски, текстом — на языке вопроса.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Lang:
    code: str
    name: str  # для указания модели, по-русски
    native: str  # для интерфейса
    stt: str | None  # код распознавания SpeechKit; None — нет
    voice: str | None  # голос синтеза SpeechKit; None — нет
    tts_lang: str | None = None


LANGS: dict[str, Lang] = {
    "ru": Lang("ru", "русский", "Русский", "ru-RU", None, "ru-RU"),  # голос по умолчанию — TTS_VOICE (D-15)
    "uz": Lang("uz", "узбекский (латиница)", "Oʻzbekcha", "uz-UZ", "nigora", "uz-UZ"),
    "uz-cyrl": Lang("uz-cyrl", "узбекский (кириллица)", "Ўзбекча", "uz-UZ", "nigora", "uz-UZ"),
    "tg": Lang("tg", "таджикский (кириллица)", "Тоҷикӣ", None, None),
    "kk": Lang("kk", "казахский (кириллица)", "Қазақша", "kk-KZ", "amira", "kk-KZ"),
    "ky": Lang("ky", "киргизский (кириллица)", "Кыргызча", None, None),
    "en": Lang("en", "английский", "English", "en-US", "john", "en-US"),
    "hi": Lang("hi", "хинди", "हिन्दी", None, None),  # решение Валерия 27.11: текстом; голоса у SpeechKit нет
}
ALIASES = {"tj": "tg", "kz": "kk", "kg": "ky", "uzb": "uz", "uz-latn": "uz", "rus": "ru", "eng": "en", "hin": "hi"}

# Буквы, которых нет в русском: по ним язык кириллического текста узнаётся почти наверняка.
_TG = re.compile(r"[ӣӯҷҶӢӮ]")
_UZ_CYRL = re.compile(r"[ўЎ]")
_KK = re.compile(r"[әӘұҰіІ]")
_KY_KK = re.compile(r"[өӨүҮңҢ]")
_TG_UZ = re.compile(r"[ҳҲқҚғҒ]")
_CYR = re.compile(r"[А-Яа-яЁёЎўҚқҒғҲҳӢӣӮӯҶҷӘәӨөҮүҰұҢңІі]")
_LAT = re.compile(r"[A-Za-z]")
_DEVA = re.compile(r"[\u0900-\u097F]")
# хинглиш — хинди латиницей: служебные слова, которых нет в английском
_HINGLISH = re.compile(
    r"\b(?:hai|hain|kya|kaise|kaisa|kitna|kitni|kitne|kare|karna|karein|karu|mein|ka|ki|ke|ko|nahi|nahin|bhai|"
    r"aur|se|kab|kaun|kahan|chahiye|wala|wali|abhi|yeh|ye|woh|matlab)\b",
    re.I,
)
_UZ_LAT = re.compile(
    r"\b(?:va|bu|qancha|qanday|qaysi|nima|kerak|bo['‘ʻ’]?l|dvigatel\w*|uchun|bilan|emas|mumkin|qilish|"
    r"o['‘ʻ’]rnat\w*|tekshir\w*|almashtir\w*|moment\w*|tortish|mashina\w*|yurish|necha|qachon)\b|[oOgG]['‘ʻ’]",
    re.I,
)
_EN = re.compile(r"\b(?:the|what|how|is|are|of|engine|valve|torque|can|should|which|check)\b", re.I)
_KY_WORDS = re.compile(r"\b(?:кандай|канча|кайсы|болот|керек|эмне|кантип|менен|үчүн|жана)\b", re.I)


def normalize(code: str | None) -> str | None:
    """Код от интерфейса или модели → наш код; неизвестный — None (язык определит код)."""
    if not code:
        return None
    c = ALIASES.get(code.strip().lower(), code.strip().lower())
    if c in LANGS:
        return c
    c = c.split("-")[0].split("_")[0]
    c = ALIASES.get(c, c)
    return c if c in LANGS else None


def detect(text: str) -> str | None:
    """Язык вопроса по буквам и словам: ru, uz, uz-cyrl, tg, kk, ky, en. Не уверен — None (решит план модели).

    Ломаный русский — русский: ответ ему по-русски."""
    if not text.strip():
        return None
    cyr, lat, deva = len(_CYR.findall(text)), len(_LAT.findall(text)), len(_DEVA.findall(text))
    if deva > cyr and deva >= lat:
        return "hi"
    if lat > cyr:
        if len(_UZ_LAT.findall(text)) >= 2:
            return "uz"
        hinglish, english = len(_HINGLISH.findall(text)), len(_EN.findall(text))
        if hinglish >= 2 and hinglish > english:  # хинглиш — хинди, если явно не английский
            return "hi"
        if english >= 2:
            return "en"
        return None
    if _TG.search(text):
        return "tg"
    if _UZ_CYRL.search(text):
        return "uz-cyrl"
    if _KK.search(text):
        return "kk"
    if _KY_KK.search(text):
        return "kk" if _TG_UZ.search(text) else "ky"
    if _TG_UZ.search(text):
        return "uz-cyrl"
    if _KY_WORDS.search(text):
        return "ky"
    return "ru" if cyr else None


def instruction(code: str) -> str:
    """Указание модели рядом с вопросом. Для русского — пусто: так ответы на русском не меняются."""
    if code == "ru" or code not in LANGS:
        return ""
    name = LANGS[code].name
    script = {"uz": " Пиши латиницей.", "en": "", "hi": " Пиши деванагари."}.get(code, " Пиши кириллицей.")
    return (
        f"Язык ответа: {name}. Весь ответ — на этом языке, включая шаги и строки «Понадобится», «Безопасность» "
        f"(их тоже переведи).{script} Без изменений, как в руководстве: числа, диапазоны, единицы измерения, "
        "обозначения деталей и ссылки [R…]. Дословную цитату из руководства давай по-русски в кавычках «…», "
        "а сразу за ней — перевод в скобках."
    )


def matches(answer: str, code: str) -> bool:
    """Ответ на нужном языке? Грубо и с запасом: цитаты по-русски допустимы, проверяется основной текст."""
    if code == "ru" or code not in LANGS:
        return True
    body = re.sub(r"«[^»]*»|\[R\d+\]", " ", answer)  # цитаты руководства — по-русски, это нормально
    cyr, lat = len(_CYR.findall(body)), len(_LAT.findall(body))
    if code == "hi":
        return len(_DEVA.findall(body)) > cyr
    if code in ("uz", "en"):
        return lat > cyr
    if cyr <= lat:
        return False
    found = detect(body)
    if code == "uz-cyrl":
        return found in ("uz-cyrl", "tg")  # ҳ қ ғ — общие буквы; ў бывает не в каждой фразе
    if code == "ky":
        return found in ("ky", "kk")
    return found == code


_UZ_TRANSLIT = {
    "ш": "sh", "ч": "ch", "ю": "yu", "я": "ya", "ё": "yo", "ц": "ts", "щ": "sh", "ў": "oʻ", "ғ": "gʻ",
    "қ": "q", "ҳ": "h", "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ф": "f", "х": "x", "ъ": "ʼ", "ь": "", "ы": "i", "э": "e",
}  # fmt: skip


def uz_to_latin(text: str) -> str:
    """Узбекская кириллица → латиница (таблица, не модель): голос nigora читает латиницу.
    «е» в начале слова и после гласной — «ye», как в узбекской орфографии."""
    out: list[str] = []
    prev = ""
    for ch in text:
        low = ch.lower()
        if low == "е" and (not prev.isalpha() or prev.lower() in "аеёиоуэюяў"):
            lat = "ye"
        else:
            lat = _UZ_TRANSLIT.get(low, ch)
        if ch != low and lat:
            lat = lat[0].upper() + lat[1:]
        out.append(lat)
        prev = ch
    return "".join(out)


# Готовые фразы кода в короткой версии для озвучки.
SOURCE_TAIL = {
    "ru": "Источник: {manual}, страница {page}.",
    "uz": "Manba: {manual}, {page}-sahifa.",
    "uz-cyrl": "Манба: {manual}, {page}-саҳифа.",
    "kk": "Дереккөз: {manual}, {page}-бет.",
    "en": "Source: {manual}, page {page}.",
}
NOT_IN_MANUAL = {
    "ru": "В руководстве этого нет — нужна дефектовка.",
    "uz": "Qoʻllanmada bu yoʻq — defektovka kerak.",
    "uz-cyrl": "Қўлланмада бу йўқ — дефектовка керак.",
    "kk": "Нұсқаулықта бұл жоқ — дефектовка қажет.",
    "en": "This is not in the manual — a defect inspection is needed.",
}
NO_VOICE = "Озвучки на языке «{name}» нет — ответ на экране на вашем языке."


def voice_for(code: str | None) -> Lang | None:
    """Язык с голосом SpeechKit; нет голоса — None (озвучка по-русски, текст — на языке вопроса)."""
    lang = LANGS.get(code or "")
    return lang if lang is not None and lang.voice else None
