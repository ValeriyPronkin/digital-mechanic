"""Голос на стенде, как его делает страница: WAV 16 кГц → распознавание → чат → озвучка.

python scripts/stand_voice.py https://<стенд>/  — код 0, если все три шага ответили 200 и озвучка — mp3.
Вопрос синтезируется SpeechKit (ключ YANDEX_TTS_API_KEY / YANDEX_API_KEY в окружении запуска). ≈0,5 ₽.
Печатает по каждому шагу: код, время, размер, заголовки ответа — для разбора обрывов («Load failed» в Safari).
"""

from __future__ import annotations

import io
import os
import sys
import time
import wave

import httpx

QUESTION = "Какой тепловой зазор клапанов?"
VEHICLE, SESSION = "M333YK47", "S-0005"


def question_wav(key: str) -> bytes:
    r = httpx.post(
        "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize",
        headers={"Authorization": f"Api-Key {key}"},
        data={"text": QUESTION, "lang": "ru-RU", "voice": "ermil", "format": "lpcm", "sampleRateHertz": "16000"},
        timeout=60,
    )
    r.raise_for_status()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(r.content)
    return buf.getvalue()


def step(name: str, fn: object) -> httpx.Response | None:
    t = time.monotonic()
    try:
        r: httpx.Response = fn()  # type: ignore[operator]
    except httpx.HTTPError as exc:
        print(f"{name}: ОБРЫВ через {time.monotonic() - t:.1f} с — {type(exc).__name__}: {exc}")
        return None
    hdr = {k: v for k, v in r.headers.items() if k.lower() not in ("set-cookie",)}
    print(f"{name}: {r.status_code} за {time.monotonic() - t:.1f} с, {len(r.content)} байт, http={r.http_version}")
    print(f"  заголовки: {hdr}")
    if r.headers.get("content-type", "").startswith("application/json"):
        print(f"  тело: {r.text[:600]}")
    return r


def main(url: str) -> int:
    base = url.rstrip("/")
    key = os.environ.get("YANDEX_TTS_API_KEY") or os.environ.get("YANDEX_API_KEY") or ""
    if not key:
        print("нет ключа SpeechKit для синтеза вопроса", file=sys.stderr)
        return 2
    audio = question_wav(key)
    print(f"вопрос: «{QUESTION}», WAV {len(audio)} байт")
    ok = True
    with httpx.Client(timeout=180, http2=False) as c:
        rec = step(
            "recognize",
            lambda: c.post(f"{base}/api/voice/recognize", content=audio, headers={"Content-Type": "audio/wav"}),
        )
        if rec is None or rec.status_code != 200:
            return 1
        text = rec.json()["text"]
        chat = step(
            "chat",
            lambda: c.post(f"{base}/api/chat", json={"vehicle_id": VEHICLE, "session_id": SESSION, "message": text}),
        )
        if chat is None or chat.status_code != 200:
            return 1
        sp = chat.json()["speech"]
        print(f"  вслух: {sp['text']}")
        mp3 = step("speak", lambda: c.post(f"{base}/api/voice/speak", json=sp))
        ok = mp3 is not None and mp3.status_code == 200 and mp3.headers.get("content-type") == "audio/mpeg"
    print("голос:", "ок" if ok else "НЕ ПРОШЁЛ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
