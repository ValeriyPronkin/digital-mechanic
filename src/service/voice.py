"""Голос (issue #14): вопрос голосом — распознавание SpeechKit, ответ вслух — короткая версия синтезом SpeechKit.

Ключ SpeechKit только на сервере (`YANDEX_TTS_API_KEY`, иначе `YANDEX_API_KEY`). Браузер шлёт WAV PCM 16 кГц моно
(WebAudio; MediaRecorder на iPhone даёт mp4, его SpeechKit не принимает). Короткую версию для озвучки собирает код
из уже проверенного ответа агента (guard): берётся предложение со ссылкой [R…], и каждая цифра в нём должна быть
во фрагменте этой ссылки; иначе — «в руководстве нет» или предложение без цифр. Синтезируется только текст,
подписанный сервером (`conv_state.sign_text`), — открытого синтеза произвольного текста нет.
"""

from __future__ import annotations

import io
import os
import re
import time
import wave
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import numpy as np

from service.agent import Source, numbers
from service.clients import ServiceError

STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
SAMPLE_RATE = 16_000
MAX_SECONDS = 30
MAX_WAV_BYTES = 44 + SAMPLE_RATE * 2 * MAX_SECONDS + 4096
SILENCE_PEAK = 300  # из 32767: тише — считаем, что механик ничего не сказал
NOT_HEARD = "Не расслышал, повторите."
NOT_IN_MANUAL = "В руководстве этого нет — нужна дефектовка."
SPEECH_MAX_CHARS = 260


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
    def recognize(self, pcm: bytes) -> str: ...

    def synthesize(self, text: str) -> bytes: ...


class SpeechKit:
    def __init__(self, key: str, http: httpx.Client | None = None) -> None:
        self.key = key
        self.http = http or httpx.Client(timeout=30)
        self.voice = os.environ.get("TTS_VOICE", "filipp")  # D-14: ждёт выбора человека (#18)
        self.speed = os.environ.get("TTS_SPEED", "0.95")

    @classmethod
    def from_env(cls) -> SpeechKit:
        key = (os.environ.get("YANDEX_TTS_API_KEY") or os.environ.get("YANDEX_API_KEY") or "").strip()
        if not key:
            raise VoiceUnavailableError("Голос сейчас недоступен — задайте вопрос текстом.")
        return cls(key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Api-Key {self.key}"}

    def recognize(self, pcm: bytes) -> str:
        params = {"lang": "ru-RU", "topic": "general", "format": "lpcm", "sampleRateHertz": str(SAMPLE_RATE)}
        try:
            r = self.http.post(STT_URL, params=params, content=pcm, headers=self._headers())
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError("Распознавание не ответило — повторите или спросите текстом.") from exc
        if r.status_code != 200:
            raise VoiceUnavailableError(f"Распознавание не сработало (HTTP {r.status_code}) — спросите текстом.")
        return str(r.json().get("result", "")).strip()

    def synthesize(self, text: str) -> bytes:
        data = {"text": for_tts(text), "lang": "ru-RU", "voice": self.voice, "speed": self.speed, "format": "mp3"}
        try:
            r = self.http.post(TTS_URL, data=data, headers=self._headers())
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError("Озвучка не ответила — ответ на экране.") from exc
        if r.status_code != 200:
            raise VoiceUnavailableError(f"Озвучка не сработала (HTTP {r.status_code}) — ответ на экране.")
        return r.content


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


# ---------- короткая версия ответа ----------

_REF = re.compile(r"\[\s*(R\d+)\s*\]")
_REF_GROUP = re.compile(r"\s*\[\s*R\d+\s*\](?:\s*[,;]?\s*\[\s*R\d+\s*\])*")  # «[R1], [R3]» целиком
_MD = re.compile(r"[*_#`>]+")
# «в руководстве не нашёл», «в руководстве по этому двигателю (ЯМЗ-236М2) данных … нет» — в пределах предложения
_NOT_FOUND = re.compile(
    r"не\s+наш[её]л|нет\s+в\s+руководств|руководств\w*[^.!?\n]{0,160}?\b(?:нет|не\s+приводится|не\s+указан\w*)\b",
    re.IGNORECASE,
)
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


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


def speech_for(answer: str, sources: dict[str, Source]) -> Speech:
    """Короткая версия для озвучки из проверенного ответа. Каждая цифра в `body` — во фрагменте своей ссылки."""
    fallback: str | None = None
    for raw in _SENT.split(answer):
        refs = tuple(r for r in _REF.findall(raw) if r in sources)
        text = _clean(_REF_GROUP.sub("", raw))
        if len(text) < 8:
            continue
        nums = numbers(text)
        if refs:
            allowed: set[str] = set().union(*(numbers(sources[r].text) for r in refs))
            if nums <= allowed and len(text) <= SPEECH_MAX_CHARS:
                src = sources[refs[0]]
                tail = f"Источник: {short_manual(src.manual)}, страница {src.pdf_page}."
                return Speech(f"{text.rstrip('.')}. {tail}", text, refs)
        elif fallback is None and not nums and len(text) <= SPEECH_MAX_CHARS:
            fallback = text
    if _NOT_FOUND.search(answer) or not fallback:
        return Speech(NOT_IN_MANUAL, NOT_IN_MANUAL, ())
    return Speech(fallback, fallback, ())


# ---------- расход ----------


def stt_cost_rub(seconds: float) -> float:
    """Синхронное распознавание тарифицируется блоками по 15 с (цена — допущение, `STT_PRICE_RUB_PER_15S`)."""
    blocks = max(1, int(np.ceil(seconds / 15)))
    return blocks * float(os.environ.get("STT_PRICE_RUB_PER_15S", "0.16"))


def tts_cost_rub(chars: int) -> float:
    """Синтез — за символы (цена — допущение, `TTS_PRICE_RUB_PER_1K_CHARS`)."""
    return chars / 1000 * float(os.environ.get("TTS_PRICE_RUB_PER_1K_CHARS", "1.32"))


def timed(fn: Any, *args: Any) -> tuple[Any, int]:
    t = time.monotonic()
    out = fn(*args)
    return out, int((time.monotonic() - t) * 1000)
