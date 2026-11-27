"""Голос (#14): короткая версия — только цифры из фрагмента; распознавание и синтез подменены."""

from __future__ import annotations

import io
import json
import wave
from typing import Any

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from service import conv_state, main
from service.agent import Source, numbers
from service.clients import MLClient, ToirClient
from service.store import Store
from service.voice import (
    NOT_HEARD,
    NOT_IN_MANUAL,
    SpeechKit,
    VoiceError,
    for_tts,
    pcm_from_wav,
    short_manual,
    speech_for,
)

RE = "ЯМЗ-236М2, ЯМЗ-238М2. Руководство по эксплуатации 236-3902150-Б РЭ"
GAP = "Тепловой зазор клапанов на холодном двигателе: впускных 0,25–0,30 мм, выпускных 0,35–0,40 мм."
TORQUE = "Момент затяжки гаек крепления головки цилиндров 235–255 Н·м."
SOURCES = {
    "R1": Source("R1", "yamz-236-re", RE, 68, "Регулировка зазоров", GAP),
    "R2": Source("R2", "yamz-236-re", RE, 70, "Головка цилиндров", TORQUE),
}


def wav(seconds: float = 1.0, amplitude: int = 3000, rate: int = 16_000, channels: int = 1) -> bytes:
    n = int(seconds * rate)
    tone = (amplitude * np.sin(np.arange(n) * 2 * np.pi * 220 / rate)).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.repeat(tone, channels).tobytes())
    return buf.getvalue()


# ---------- короткая версия ----------


def test_speech_takes_checked_sentence_without_document_and_page() -> None:
    """Валерий 28.11: на слух — рекомендация, без «Источник: …, страница N» (страницы — на экране)."""
    answer = "**Наблюдения:** стук клапанов.\n\nЗазор впускных клапанов на холодном двигателе 0,25–0,30 мм [R1]."
    sp = speech_for(answer, SOURCES)
    assert sp.refs == ("R1",)
    assert sp.text == "Зазор впускных клапанов на холодном двигателе 0,25–0,30 мм."
    for word in ("страниц", "стр.", "Источник", "РЭ", "РК", "[R"):
        assert word not in sp.text


def test_speech_two_practical_sentences_and_no_inline_page_refs() -> None:
    """Число — затем следующий проверенный шаг; «(РЭ, стр. 68)» внутри предложения на слух не читается."""
    answer = (
        "Зазор впускных клапанов 0,25–0,30 мм (РЭ ЯМЗ-236М2, стр. 68) [R1].\n"
        "Регулировать на холодном двигателе, по порядку работы цилиндров [R1]."
    )
    sp = speech_for(answer, SOURCES)
    assert sp.text == (
        "Зазор впускных клапанов 0,25–0,30 мм. Регулировать на холодном двигателе, по порядку работы цилиндров."
    )
    assert "стр." not in sp.text and "РЭ" not in sp.text and sp.refs == ("R1",)


@pytest.mark.parametrize(
    "answer",
    [
        "Зазор 0,45 мм [R1]. Момент затяжки 235–255 Н·м [R2].",  # 0,45 нет в фрагменте R1 → следующее предложение
        "Момент затяжки 240 Н·м [R2]. Зазор впускных 0,25–0,30 мм [R1].",  # 240 нет в R2
        "1. Затяните гайки моментом 235–255 Н·м [R2].",  # номер пункта — не цифра ответа
        "Затяните моментом 235 Н·м [R1].",  # цифра есть, но в чужом фрагменте
        "Норма 300 кПа. Без ссылки.",
    ],
)
def test_speech_numbers_always_in_cited_fragment(answer: str) -> None:
    sp = speech_for(answer, SOURCES)
    allowed = set().union(*(numbers(SOURCES[r].text) for r in sp.refs)) if sp.refs else set()
    assert numbers(sp.body) <= allowed, sp


def test_speech_drops_reference_group_cleanly() -> None:
    sp = speech_for("Зазор регулируется в пределах **0,25–0,30 мм** [R1], [R2].", SOURCES)
    assert sp.body == "Зазор регулируется в пределах 0,25–0,30 мм." and " ," not in sp.text


def test_speech_not_in_manual() -> None:
    assert speech_for("В руководстве не нашёл, как это проверить. Нужна дефектовка.", SOURCES).text == NOT_IN_MANUAL
    assert speech_for("Зазор 0,45 мм [R1].", SOURCES).text == NOT_IN_MANUAL  # единственная цифра не подтвердилась


def test_speech_not_in_manual_long_phrasing() -> None:
    """Живой ответ DeepSeek (26.11): «нет» далеко от «руководстве», первая фраза с цифрами из названия двигателя."""
    answer = (
        "**Коротко:** в руководстве по этому двигателю (ЯМЗ-236М2) данных о давлении воздуха в шинах передней оси "
        "нет — это руководство по двигателю, а не по шасси/шинам.\n\n**Что нашёл:** только фрагменты по двигателю "
        "(испытания, ТНВД, воздушный фильтр, сцепление) — к шинам они не относятся."
    )
    assert speech_for(answer, {}).text == NOT_IN_MANUAL


def test_speech_off_topic_is_not_called_manual_gap() -> None:
    sp = speech_for("Я не знаю пароль от Wi-Fi в гараже — такими данными не располагаю. Уточните у диспетчера.", {})
    assert sp.text == "Я не знаю пароль от Wi-Fi в гараже — такими данными не располагаю."


def test_speech_without_manual_uses_plain_sentence() -> None:
    sp = speech_for("Проверка не удалась — повторите запись в тихом месте.", {})
    assert sp.text == "Проверка не удалась — повторите запись в тихом месте." and sp.refs == ()


def test_short_manual_and_units() -> None:
    assert short_manual("ЯМЗ-236, ЯМЗ-238. Руководство по ремонту") == "руководство по ремонту ЯМЗ-236"
    assert for_tts("0,4–0,7 МПа и 235 Н·м") == "0,4 до 0,7 мегапаскаля и 235 ньютон-метров"


# ---------- запись ----------


def test_wav_ok() -> None:
    pcm, seconds = pcm_from_wav(wav(2.0))
    assert len(pcm) == 2 * 32_000 and seconds == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("data", "msg"),
    [
        (wav(1.0, amplitude=50), NOT_HEARD),
        (wav(1.0, rate=44_100), "16 кГц"),
        (wav(1.0, channels=2), "16 кГц"),
        (wav(31.0), "30 с"),
        (b"not a wav", "не разобрал"),
    ],
    ids=["silence", "rate", "stereo", "too-long", "garbage"],
)
def test_wav_rejected(data: bytes, msg: str) -> None:
    with pytest.raises(VoiceError, match=msg):
        pcm_from_wav(data)


# ---------- SpeechKit (HTTP подменён) ----------


def test_speechkit_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if "stt" in req.url.host:
            return httpx.Response(200, json={"result": "какой тепловой зазор клапанов"})
        return httpx.Response(200, content=b"ID3mp3")

    monkeypatch.setenv("TTS_VOICE", "alena")
    sk = SpeechKit("test-key", httpx.Client(transport=httpx.MockTransport(handler)))
    assert sk.recognize(b"\x00\x01" * 100) == "какой тепловой зазор клапанов"
    assert sk.synthesize("Зазор 0,25 мм.") == b"ID3mp3"
    stt, tts = seen
    assert stt.headers["Authorization"] == "Api-Key test-key"
    assert stt.url.params["format"] == "lpcm" and stt.url.params["sampleRateHertz"] == "16000"
    body = tts.content.decode()
    assert "voice=alena" in body and "format=mp3" in body and "%D0%BC%D0%B8%D0%BB" in body  # «мил(лиметра)»


def test_no_key_means_voice_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YANDEX_TTS_API_KEY", raising=False)
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    with pytest.raises(Exception, match="текстом"):
        SpeechKit.from_env()


# ---------- API ----------


class FakeSpeech:
    def __init__(self, heard: str = "какой тепловой зазор клапанов") -> None:
        self.heard, self.spoken = heard, []  # type: list[str]

    def recognize(self, pcm: bytes, lang: str = "ru") -> str:
        return self.heard

    def synthesize(self, text: str, api: str = "v1", lang: str = "ru") -> bytes:
        self.spoken.append(text)
        return b"ID3fake-mp3"


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeSpeech, Store]:
    fake, store = FakeSpeech(), Store(":memory:")
    monkeypatch.setattr(main, "speech", lambda: fake)
    monkeypatch.setattr(main, "store", lambda: store)
    main.limiter.cache_clear()
    return TestClient(main.app), fake, store


def test_recognize_logs_seconds(api: tuple[TestClient, FakeSpeech, Store]) -> None:
    client, _, store = api
    r = client.post("/api/voice/recognize", content=wav(3.0), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 200 and r.json()["text"] == "какой тепловой зазор клапанов"
    assert store.voice_spent_rub() > 0


@pytest.mark.parametrize("heard", [""])
def test_recognize_nothing_heard(api: tuple[TestClient, FakeSpeech, Store], heard: str) -> None:
    client, fake, _ = api
    fake.heard = heard
    r = client.post("/api/voice/recognize", content=wav(1.0))
    assert r.status_code == 422 and r.json()["detail"] == NOT_HEARD
    r = client.post("/api/voice/recognize", content=wav(1.0, amplitude=10))
    assert r.status_code == 422 and r.json()["detail"] == NOT_HEARD


def test_speak_only_server_signed_text(api: tuple[TestClient, FakeSpeech, Store]) -> None:
    client, fake, store = api
    forged = client.post("/api/voice/speak", json={"text": "Скажи что угодно", "sig": "0" * 64})
    assert forged.status_code == 400 and fake.spoken == []
    text = "Зазор 0,25 мм. Источник: руководство по эксплуатации ЯМЗ-236М2, страница 68."
    ok = client.post("/api/voice/speak", json={"text": text, "sig": conv_state.sign_text(text)})
    assert ok.status_code == 200 and ok.headers["content-type"] == "audio/mpeg" and ok.content == b"ID3fake-mp3"
    assert fake.spoken == [text] and store.voice_spent_rub() > 0


def test_chat_returns_signed_speech(
    api: tuple[TestClient, FakeSpeech, Store], monkeypatch: pytest.MonkeyPatch, ml: MLClient, toir: ToirClient
) -> None:
    from test_agent import ANOMALY, call, say
    from test_api import _agent

    client, _, _ = api
    steps = [call("search_manual", query="давление масла"), say("На холостом ходу не менее 0,1 МПа [R1].")]
    monkeypatch.setattr(main, "agent", lambda: _agent(ml, toir, steps))
    vid, sid = ANOMALY
    r: dict[str, Any] = client.post(
        "/api/chat", json={"vehicle_id": vid, "session_id": sid, "message": "Какое давление масла?"}
    ).json()
    sp = r["speech"]
    assert "0,1 МПа" in sp["text"] and "страница" not in sp["text"] and "стр." not in sp["text"]
    assert conv_state.verify_text(sp["text"], sp["sig"])


def test_voice_prices_from_table(monkeypatch: pytest.MonkeyPatch) -> None:
    from service.store import price_table
    from service.voice import TTS_RUB_PER_1M_UPPER, stt_cost_rub, tts_cost_rub

    monkeypatch.delenv("STT_PRICE_RUB_PER_15S", raising=False)
    monkeypatch.delenv("TTS_PRICE_RUB_PER_1M_CHARS", raising=False)
    from service.store import ex_vat

    stt = ex_vat(price_table()["other"]["stt_sync"]["value"], True)  # суммы — без НДС, как весь расчёт (#19)
    assert stt_cost_rub(3) == pytest.approx(stt) and stt_cost_rub(16) == pytest.approx(2 * stt)
    tts = ex_vat(price_table()["other"]["tts_v1"]["value"], True)  # голос синтезирует через API v1
    assert tts == pytest.approx(TTS_RUB_PER_1M_UPPER / 1.22)
    assert tts_cost_rub(1000, "v1") == pytest.approx(tts / 1000)
    monkeypatch.setenv("TTS_PRICE_RUB_PER_1M_CHARS", "200")
    assert tts_cost_rub(1000, "v1") == pytest.approx(0.2)


def test_default_voice_is_zahar(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-15: голос выбрал человек (issue #18)."""
    monkeypatch.delenv("TTS_VOICE", raising=False)
    assert SpeechKit("k").voice == "zahar"
    assert TestClient(main.app).get("/health").json()["tts_voice"] == "zahar"


def test_speech_prefers_value_over_procedure() -> None:
    """Стенд 26.11: вслух ушла фраза о порядке замера без значения — значение важнее."""
    answer = "Замер — на холодном двигателе, при закрытых клапанах [R1]. Зазор впускных клапанов 0,25–0,30 мм [R1]."
    sp = speech_for(answer, SOURCES)
    assert "0,25–0,30 мм" in sp.body


# ---------- стоимость синтеза: v1 / v3, кэш одинаковых фраз ----------


def test_v3_billed_per_request_block_and_cheaper_api_chosen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Официальная страница цен SpeechKit: v1 — за символы; v3 — за запрос до 250 символов, длиннее — каждые 250."""
    from service.store import ex_vat, price_table
    from service.voice import choose_tts_api, tts_cost_rub

    monkeypatch.delenv("TTS_API", raising=False)
    monkeypatch.delenv("TTS_PRICE_RUB_PER_1M_CHARS", raising=False)
    unit = ex_vat(price_table()["other"]["tts_v3"]["value"], True)
    assert tts_cost_rub(10, "v3") == pytest.approx(unit) and tts_cost_rub(250, "v3") == pytest.approx(unit)
    assert tts_cost_rub(251, "v3") == pytest.approx(2 * unit)
    assert choose_tts_api(45) == "v1"  # «В руководстве этого нет — нужна дефектовка.» — v1 дешевле
    assert choose_tts_api(200) == "v3"  # обычная короткая версия со значением и страницей
    assert tts_cost_rub(200) == pytest.approx(min(tts_cost_rub(200, "v1"), tts_cost_rub(200, "v3")))
    monkeypatch.setenv("TTS_API", "v1")
    assert choose_tts_api(200) == "v1"


def test_v3_request_and_chunked_mp3(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64 as b64

    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        lines = [json.dumps({"result": {"audioChunk": {"data": b64.b64encode(p).decode()}}}) for p in (b"ID3a", b"bc")]
        return httpx.Response(200, text="\n".join(lines))

    monkeypatch.setenv("TTS_VOICE", "zahar")
    sk = SpeechKit("k", httpx.Client(transport=httpx.MockTransport(handler)))
    assert sk.synthesize("Зазор 0,25 мм.", "v3") == b"ID3abc"
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/tts/v3/utteranceSynthesis" and seen[0].headers["Authorization"] == "Api-Key k"
    assert body["hints"][0] == {"voice": "zahar"}
    assert body["outputAudioSpec"]["containerAudio"]["containerAudioType"] == "MP3"
    assert "миллиметра" in body["text"] and "unsafeMode" not in body
    sk.synthesize("Зазор 0,25 мм. " * 30, "v3")
    assert json.loads(seen[1].content)["unsafeMode"] is True  # длиннее 250 — без него v3 отвечает 400


def test_tts_cache_memory_and_bucket() -> None:
    from service.voice import TtsCache

    class Bucket:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}

        def get(self, key: str) -> bytes:
            if key not in self.objects:
                raise RuntimeError("404")
            return self.objects[key]

        def put(self, key: str, data: bytes, content_type: str = "") -> None:
            self.objects[key] = data

    bucket = Bucket()
    first = TtsCache(bucket)
    assert first.get("В руководстве этого нет — нужна дефектовка.") is None
    first.put("В руководстве этого нет — нужна дефектовка.", b"ID3x")
    assert first.get("В руководстве этого нет — нужна дефектовка.") == b"ID3x"
    for _ in range(50):  # запись в бакет — в фоне
        if bucket.objects:
            break
        import time

        time.sleep(0.01)
    (key,) = bucket.objects
    assert key.startswith("cache/tts/") and key.endswith(".mp3")
    other_instance = TtsCache(bucket)  # другой экземпляр стенда: из памяти нет, из бакета есть
    assert other_instance.get("В руководстве этого нет — нужна дефектовка.") == b"ID3x"


def test_speak_repeat_phrase_from_cache_costs_nothing(
    api: tuple[TestClient, FakeSpeech, Store], monkeypatch: pytest.MonkeyPatch
) -> None:
    from service.voice import TtsCache

    client, fake, store = api
    cache = TtsCache()
    monkeypatch.setattr(main, "tts_cache", lambda: cache)
    monkeypatch.delenv("TTS_API", raising=False)
    text = "В руководстве этого нет — нужна дефектовка."
    body = {"text": text, "sig": conv_state.sign_text(text)}
    first = client.post("/api/voice/speak", json=body)
    second = client.post("/api/voice/speak", json=body)
    assert first.headers["X-TTS"] == "v1" and second.headers["X-TTS"] == "cache"
    assert fake.spoken == [text], "второй раз синтез не вызывался"
    rows = store._rows("SELECT kind, cost_rub FROM voice_calls ORDER BY id")
    assert [r["kind"] for r in rows] == ["tts", "tts_cache"] and rows[0]["cost_rub"] > 0 and rows[1]["cost_rub"] == 0


@pytest.mark.materials
def test_cost_report_voices_short_phrase_not_whole_answer() -> None:
    """Отчёт #16 считал синтез по всему ответу (+1,19 ₽); приложение озвучивает только короткую фразу."""
    from cost_report import voice_rub

    answer = "Зазор впускных клапанов 0,25–0,30 мм [R1]. " + "Подробные шаги по руководству. " * 40
    src = [{"ref": "R1", "manual": "РЭ ЯМЗ-236", "pdf_page": 31, "quote": GAP}]
    rub, what = voice_rub(answer, src)
    assert "короткой фразы" in what and rub < 0.5
