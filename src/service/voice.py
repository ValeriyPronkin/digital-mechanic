"""Голос (issue #14): вопрос голосом — распознавание SpeechKit, ответ вслух — короткая версия синтезом SpeechKit.

Ключ SpeechKit только на сервере (`YANDEX_TTS_API_KEY`, иначе `YANDEX_API_KEY`). Браузер шлёт WAV PCM 16 кГц моно
(WebAudio; MediaRecorder на iPhone даёт mp4, его SpeechKit не принимает). Короткую версию для озвучки собирает код
из уже проверенного ответа агента (guard): берётся предложение со ссылкой [R…], и каждая цифра в нём должна быть
во фрагменте этой ссылки; иначе — «в руководстве нет» или предложение без цифр. Синтезируется только текст,
подписанный сервером (`conv_state.sign_text`), — открытого синтеза произвольного текста нет.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import math
import os
import re
import threading
import time
import wave
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import numpy as np

from service import language
from service.agent import Source, numbers
from service.clients import ServiceError

STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
TTS_V3_URL = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"
TTS_V3_BLOCK = 250  # v3: запрос до 250 символов — одна единица; длиннее — unsafeMode, каждые 250 — единица
SAMPLE_RATE = 16_000
MAX_SECONDS = 30
MAX_WAV_BYTES = 44 + SAMPLE_RATE * 2 * MAX_SECONDS + 4096
SILENCE_PEAK = 300  # из 32767: тише — считаем, что механик ничего не сказал
NOT_HEARD = "Не расслышал, повторите."
NOT_IN_MANUAL = "В руководстве этого нет — нужна дефектовка."
SPEECH_MAX_CHARS = 260
DEFAULT_VOICE = "zahar"  # D-15: выбор Валерия (#18), запасной — ermil


class VoiceError(ServiceError):
    http_status = 422


class VoiceUnavailableError(ServiceError):
    http_status = 503


# ---------- запись ----------


def pcm_from_wav(data: bytes) -> tuple[bytes, float]:
    """WAV из браузера → (PCM 16 бит, секунды). Только 16 кГц моно, до 30 с; тишина — VoiceError."""
    if len(data) > MAX_WAV_BYTES:
        raise VoiceError(f"Фраза длиннее {MAX_SECONDS} с — скажите короче.")
    try:
        with wave.open(io.BytesIO(data)) as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, SAMPLE_RATE):
                raise VoiceError("Запись не в том формате: нужен WAV 16 кГц моно.")
            pcm = w.readframes(w.getnframes())
            seconds = w.getnframes() / SAMPLE_RATE
    except (wave.Error, EOFError) as exc:
        raise VoiceError("Запись не разобрал — нажмите кнопку и скажите ещё раз.") from exc
    if seconds > MAX_SECONDS + 0.5:
        raise VoiceError(f"Фраза длиннее {MAX_SECONDS} с — скажите короче.")
    samples = np.frombuffer(pcm, dtype="<i2")
    if samples.size == 0 or int(np.abs(samples.astype(np.int32)).max()) < SILENCE_PEAK:
        raise VoiceError(NOT_HEARD)
    return pcm, seconds


# ---------- SpeechKit ----------


class SpeechClient(Protocol):
    def recognize(self, pcm: bytes, lang: str = "ru") -> str: ...

    def synthesize(self, text: str, api: str = "v1", lang: str = "ru") -> bytes: ...


class SpeechKit:
    def __init__(self, key: str, http: httpx.Client | None = None) -> None:
        self.key = key
        self.http = http or httpx.Client(timeout=30)
        self.voice = os.environ.get("TTS_VOICE", DEFAULT_VOICE)
        self.speed = os.environ.get("TTS_SPEED", "0.95")

    @classmethod
    def from_env(cls) -> SpeechKit:
        key = (os.environ.get("YANDEX_TTS_API_KEY") or os.environ.get("YANDEX_API_KEY") or "").strip()
        if not key:
            raise VoiceUnavailableError("Голос сейчас недоступен — задайте вопрос текстом.")
        return cls(key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Api-Key {self.key}"}

    def recognize(self, pcm: bytes, lang: str = "ru") -> str:
        """`lang` — язык, выбранный механиком; без распознавания на этом языке (tg, ky) — русский."""
        code = (language.LANGS.get(lang) or language.LANGS["ru"]).stt or "ru-RU"
        params = {"lang": code, "topic": "general", "format": "lpcm", "sampleRateHertz": str(SAMPLE_RATE)}
        try:
            r = self.http.post(STT_URL, params=params, content=pcm, headers=self._headers())
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError("Распознавание не ответило — повторите или спросите текстом.") from exc
        if r.status_code != 200:
            raise VoiceUnavailableError(f"Распознавание не сработало (HTTP {r.status_code}) — спросите текстом.")
        return str(r.json().get("result", "")).strip()

    def synthesize(self, text: str, api: str = "v1", lang: str = "ru") -> bytes:
        """mp3 короткой версии. `api` — v1 (за символы) или v3 (за запрос до 250 символов); выбор — `choose_tts_api`.
        `lang` — язык ответа: узбекский — голос nigora (кириллица — в латиницу кодом), казахский — amira,
        английский — john; языка без голоса здесь не бывает (speech_for говорит по-русски)."""
        spoken = spoken_text(text, lang)
        voice, tts_lang = voice_and_lang(lang, self.voice)
        try:
            if api == "v3":
                return self._synthesize_v3(spoken, voice)
            data = {"text": spoken, "lang": tts_lang, "voice": voice, "speed": self.speed, "format": "mp3"}
            r = self.http.post(TTS_URL, data=data, headers=self._headers())
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError("Озвучка не ответила — ответ на экране.") from exc
        if r.status_code != 200:
            raise VoiceUnavailableError(f"Озвучка не сработала (HTTP {r.status_code}) — ответ на экране.")
        return r.content

    def _synthesize_v3(self, spoken: str, voice: str) -> bytes:
        body: dict[str, Any] = {
            "text": spoken,
            "hints": [{"voice": voice}, {"speed": float(self.speed)}],
            "outputAudioSpec": {"containerAudio": {"containerAudioType": "MP3"}},
            "loudnessNormalizationType": "LUFS",
        }
        if len(spoken) > TTS_V3_BLOCK:
            body["unsafeMode"] = True  # без него v3 отвечает 400 «Too long text» (проверено 26.11)
        r = self.http.post(TTS_V3_URL, json=body, headers=self._headers())
        if r.status_code != 200:
            raise VoiceUnavailableError(f"Озвучка не сработала (HTTP {r.status_code}) — ответ на экране.")
        audio = b""
        for line in r.text.splitlines():  # ответ — JSON по строке на кусок: result.audioChunk.data в base64
            try:
                chunk = ((json.loads(line).get("result") or {}).get("audioChunk") or {}).get("data")
            except ValueError:
                continue
            if chunk:
                audio += base64.b64decode(chunk)
        if not audio:
            raise VoiceUnavailableError("Озвучка вернула пустой ответ — ответ на экране.")
        return audio


_UNITS = [
    (r"Н\s*·?\s*м\b", "ньютон-метров"),
    (r"кгс\s*/\s*см\s*[2²]", "килограмм-сил на квадратный сантиметр"),
    (r"МПа\b", "мегапаскаля"),
    (r"кПа\b", "килопаскаля"),
    (r"мм\b", "миллиметра"),
    (r"об\s*/\s*мин\b", "оборотов в минуту"),
    (r"(\d)\s*–\s*(\d)", r"\1 до \2"),
]


def for_tts(text: str) -> str:
    """Единицы измерения словами — синтез читает «МПа» по буквам. Цифры не меняются."""
    for pat, word in _UNITS:
        text = re.sub(pat, word, text)
    return text


def voice_and_lang(lang: str, default_voice: str) -> tuple[str, str]:
    """Голос и код языка синтеза для языка ответа; языка без голоса — русский голос по умолчанию."""
    v = language.voice_for(lang)
    return (v.voice or default_voice, v.tts_lang or "ru-RU") if v else (default_voice, "ru-RU")


def speech_lang(lang: str | None) -> str:
    """Язык, которым звучит короткая версия: язык ответа, если у SpeechKit есть его голос, иначе русский."""
    return lang if lang and language.voice_for(lang) is not None else "ru"


def spoken_text(text: str, lang: str) -> str:
    """Текст, который уходит в синтез: русские единицы — словами (только для русского голоса);
    узбекская кириллица — латиницей (голос nigora читает латиницу)."""
    if language.voice_for(lang) is None:
        return for_tts(text)
    if lang == "uz-cyrl":
        return language.uz_to_latin(text)
    return text


# ---------- короткая версия ответа ----------

_REF = re.compile(r"\[\s*(R\d+)\s*\]")
_REF_GROUP = re.compile(r"\s*\[\s*R\d+\s*\](?:\s*[,;]?\s*\[\s*R\d+\s*\])*")  # «[R1], [R3]» целиком
_MD = re.compile(r"[*_#`>]+")
# «в руководстве не нашёл», «в руководстве по этому двигателю (ЯМЗ-236М2) данных … нет» — в пределах предложения
_NOT_FOUND = re.compile(
    r"не\s+наш[её]л|нет\s+в\s+руководств|руководств\w*[^.!?\n]{0,160}?\b(?:нет|не\s+приводится|не\s+указан\w*)\b",
    re.IGNORECASE,
)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[^a-zа-яё\d])|\n+")


@dataclass(frozen=True)
class Speech:
    text: str  # что произносится: короткая версия + источник
    body: str  # короткая версия без источника — её цифры сверены с фрагментом
    refs: tuple[str, ...]


def _clean(sentence: str) -> str:
    s = _MD.sub("", sentence)
    s = re.sub(r"^\s*(?:\d+[.)]|[-•–])\s+", "", s)  # маркер пункта списка — не цифра ответа
    return " ".join(s.split())


def short_manual(manual: str) -> str:
    """«ЯМЗ-236М2, ЯМЗ-238М2. Руководство по эксплуатации …» → «руководство по эксплуатации ЯМЗ-236М2»."""
    engine = re.split(r"[,.]", manual, maxsplit=1)[0].strip()
    low = manual.lower()
    kind = "руководство по ремонту" if "ремонт" in low else "руководство по эксплуатации"
    return f"{kind} {engine}" if re.search(r"\d", engine) else kind


def speech_for(answer: str, sources: dict[str, Source], lang: str = "ru") -> Speech:
    """Короткая версия для озвучки из проверенного ответа. Каждая цифра в `body` — во фрагменте своей ссылки.

    Сначала — предложение со ссылкой и цифрой (значение с единицами), затем — со ссылкой без цифр.
    Язык ответа без голоса SpeechKit (таджикский, киргизский) — честная фраза по-русски, ответ — на экране."""
    if lang != "ru" and lang in language.LANGS and language.voice_for(lang) is None:
        notice = language.NO_VOICE.format(name=language.LANGS[lang].name.split(" (")[0])
        return Speech(notice, notice, ())
    tail_tpl = language.SOURCE_TAIL.get(lang, language.SOURCE_TAIL["ru"])
    not_in_manual = language.NOT_IN_MANUAL.get(lang, NOT_IN_MANUAL)
    with_numbers: list[Speech] = []
    plain_refs: list[Speech] = []
    fallback: str | None = None
    for raw in _SENT.split(answer):
        refs = tuple(r for r in _REF.findall(raw) if r in sources)
        text = _clean(_REF_GROUP.sub("", raw))
        if len(text) < 8 or len(text) > SPEECH_MAX_CHARS:
            continue
        nums = numbers(text)
        if refs:
            allowed: set[str] = set().union(*(numbers(sources[r].text) for r in refs))
            if nums <= allowed:
                src = sources[refs[0]]
                tail = tail_tpl.format(manual=short_manual(src.manual), page=src.pdf_page)
                (with_numbers if nums else plain_refs).append(Speech(f"{text.rstrip('.')}. {tail}", text, refs))
        elif fallback is None and not nums:
            fallback = text
    if with_numbers or plain_refs:
        return (with_numbers or plain_refs)[0]
    if _NOT_FOUND.search(answer) or not fallback:
        return Speech(not_in_manual, not_in_manual, ())
    return Speech(fallback, fallback, ())


# ---------- расход ----------


# Синтез идёт через SpeechKit API v1 — тариф `tts_v1` в data/prices.json (официальная страница, #19).
# Запасное значение — та же цена с НДС, если строки в таблице нет (расход не занижается).
TTS_RUB_PER_1M_UPPER = 1342.0


def stt_cost_rub(seconds: float) -> float:
    """Синхронное распознавание — блоками по 15 с; цена — `data/prices.json` (`STT_PRICE_RUB_PER_15S` перекрывает)."""
    from service.store import ex_vat, price_table

    blocks = max(1, int(np.ceil(seconds / 15)))
    row = price_table()["other"]["stt_sync"]
    price = os.environ.get("STT_PRICE_RUB_PER_15S") or ex_vat(float(row["value"]), bool(row.get("vat_included")))
    return blocks * float(price)


def _tts_price(key: str, fallback: float) -> float:
    from service.store import ex_vat, price_table

    row = price_table()["other"].get(key)
    return ex_vat(float(row["value"]), bool(row.get("vat_included"))) if row else fallback


def tts_cost_rub(chars: int, api: str | None = None) -> float:
    """Синтез по тарифу без НДС (`data/prices.json`, официальная страница цен SpeechKit).
    v1 — за символы; v3 — за запрос: до 250 символов одна единица, длиннее (unsafeMode) — каждые начатые 250.
    `api=None` — по более дешёвому. `TTS_PRICE_RUB_PER_1M_CHARS` перекрывает цену v1."""
    override = os.environ.get("TTS_PRICE_RUB_PER_1M_CHARS")
    v1 = chars * (float(override) if override else _tts_price("tts_v1", TTS_RUB_PER_1M_UPPER)) / 1_000_000
    v3 = max(1, math.ceil(chars / TTS_V3_BLOCK)) * _tts_price("tts_v3", 0.1626)
    if api == "v1":
        return v1
    if api == "v3":
        return v3
    return min(v1, v3)


def choose_tts_api(chars: int) -> str:
    """`TTS_API=v1|v3` — принудительно; иначе дешёвый для этой длины (v1 выгоднее для фраз короче ~120 символов)."""
    forced = os.environ.get("TTS_API", "auto").strip()
    if forced in ("v1", "v3"):
        return forced
    return "v1" if tts_cost_rub(chars, "v1") <= tts_cost_rub(chars, "v3") else "v3"


def tts_voice() -> str:
    return os.environ.get("TTS_VOICE", DEFAULT_VOICE)


# ---------- кэш одинаковых фраз ----------


class TtsCache:
    """mp3 одинаковых фраз не синтезируется повторно: «В руководстве этого нет…», частые значения.

    В памяти экземпляра — всегда (до MEMORY_ITEMS фраз). На стенде (`TTS_CACHE_BUCKET=1`) — ещё и общий в бакете
    `cache/tts/<sha256>.mp3` по IAM-токену стенда (как журнал #27): повтор на другом экземпляре тоже бесплатный.
    Ключ — голос, скорость и текст, уходящий в синтез. Сбой бакета кэш не роняет: просто синтез."""

    MEMORY_ITEMS = 128

    def __init__(self, bucket: Any = None) -> None:
        self.bucket = bucket
        self._mem: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(text: str, lang: str = "ru") -> str:
        speed = os.environ.get("TTS_SPEED", "0.95")
        voice, _ = voice_and_lang(lang, tts_voice())
        raw = f"{voice}|{speed}|{spoken_text(text, lang)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, text: str, lang: str = "ru") -> bytes | None:
        k = self.key(text, lang)
        with self._lock:
            if k in self._mem:
                self._mem.move_to_end(k)
                return self._mem[k]
        if self.bucket is None:
            return None
        try:
            audio: bytes = self.bucket.get(f"cache/tts/{k}.mp3")
        except Exception:  # нет в бакете или бакет недоступен — синтезируем
            return None
        self._remember(k, audio)
        return audio

    def put(self, text: str, audio: bytes, lang: str = "ru") -> None:
        k = self.key(text, lang)
        self._remember(k, audio)
        if self.bucket is not None:
            bucket = self.bucket

            def run() -> None:
                try:
                    bucket.put(f"cache/tts/{k}.mp3", audio, "audio/mpeg")
                except Exception as exc:
                    logging.getLogger(__name__).warning("кэш озвучки не записан в бакет: %s", type(exc).__name__)

            threading.Thread(target=run, name="tts-cache", daemon=True).start()

    def _remember(self, k: str, audio: bytes) -> None:
        with self._lock:
            self._mem[k] = audio
            self._mem.move_to_end(k)
            while len(self._mem) > self.MEMORY_ITEMS:
                self._mem.popitem(last=False)

    @classmethod
    def from_env(cls) -> TtsCache:
        if os.environ.get("TTS_CACHE_BUCKET", "") != "1" or not os.environ.get("S3_BUCKET", "").strip():
            return cls()
        from service import kb_store
        from service.spend import RefreshingIamAuth

        http = httpx.Client(timeout=10)
        endpoint = os.environ.get("S3_ENDPOINT", kb_store.DEFAULT_ENDPOINT)
        return cls(kb_store.Bucket(os.environ["S3_BUCKET"].strip(), RefreshingIamAuth(http), http, endpoint))


def timed(fn: Any, *args: Any) -> tuple[Any, int]:
    t = time.monotonic()
    out = fn(*args)
    return out, int((time.monotonic() - t) * 1000)
