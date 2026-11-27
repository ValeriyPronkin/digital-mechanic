"""Видео для жюри одним непрерывным дублем (Валерий, 27.11): Playwright Chromium записывает сессию браузера на
настоящем сервере с настоящей моделью; ускоряется только ожидание ответа модели. Звук — закадровый голос диктора
(SpeechKit, голос не продукта) и настоящая озвучка ответа продуктом в сцене «Прослушать».

    make video                                   — E2E_URL (по умолчанию make run-local, :8010), тёмная тема
    make video E2E_URL=https://<стенд>/ VIDEO_ARGS="--theme light --pace 1.6"

Требования организаторов (27.11): до 3:00, один фрагмент, без монтажа; можно — подписи, стрелки и голосовой
комментарий, ускорять только ожидание ответа модели; показывать только реально работающее. Поэтому:
  • запись — одна сессия браузера, без склеек: ffmpeg только меняет скорость кусков «Готовим ответ…»
    (setpts, равномерно, ×4–8), куски по порядку, ничего не вырезается;
  • подписи — полоска внизу страницы (текст диктора), рамка — на ключевом элементе;
  • диктор: каждая фраза начинается на таймкоде своей сцены; сцена длится не меньше фразы (пауза растягивается,
    фразы не обрезаются и не накладываются). Голос диктора — не голос продукта (продукт — zahar);
  • «Прослушать»: тот же ответ `/api/voice/speak`, что продукт проигрывает по кнопке, — на момент нажатия,
    громче диктора, диктор в это время молчит;
  • сведение: дорожки диктора и продукта, нормализация громкости, AAC; видео не перекодируется заново;
  • сцены, которых на сервере нет (кнопки нет), пропускаются и попадают в список пропущенных.
Итог — reports/video/<метка>-<тема>/video.mp4 (со звуком), video-silent.mp4, исходник video.webm, scenes.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e import BUSY, DIAG, norm, session_label

ROOT = Path(__file__).resolve().parents[1]
LIMIT_S = 175.0  # ≤ 2:55 — запас до 3:00
SPEED_MIN, SPEED_MAX = 8.0, 10.0  # Валерий 27.11: ожидание — ×8–10, без пустоты на экране
WIDTH, HEIGHT = 1280, 800
GAP_S = 0.9  # сцена = фраза диктора + 0,9 с (Валерий 27.11: без мёртвых пауз)
BEAT_MAX_S = 1.2  # пауза внутри сцены — на анимацию, не на чтение: читать даёт фраза диктора
DEMO_CHECKS = [("B418HK98", "S-0009"), ("H142OX78", "S-0113"), ("M260EH47", "S-0079")]

# Текст диктора по сценам (штурман по слову Валерия, 27.11); подпись внизу экрана — тот же текст.
NARRATION: dict[str, str] = {  # Валерий 27.11: «чтобы людям было понятно, о чём речь»
    "park": "Цифровой механик — помощник механика автопарка. Приложение в телефоне: механик выбирает машину и видит "
    "результат акустической проверки двигателя.",
    "card": "Проверка нашла неисправность — клапанный механизм. Что это и насколько срочно, решают правила в коде, "
    "а не нейросеть: мгновенно и бесплатно.",
    "page": "Каждый ответ — со ссылкой на руководство по двигателю. Открываем страницу — строка, откуда взят ответ, "
    "выделена прямо в документе.",
    "question": "Механик спрашивает своими словами — голосом или текстом. Сверху короткий ответ, ниже подробности, "
    "каждая цифра сверена со страницей руководства.",
    "listen": "Ответ можно прослушать — его зачитывает сам помощник.",
    "tools": "Какой нужен инструмент и какие запчасти — помощник берёт из руководства, ничего не придумывает.",
    "ticket": "Помощник готовит заявку на дефектовку: работы и запчасти со страницами руководства. В систему ремонта "
    "она уходит, только когда механик нажал «Отправить».",
    "drive": "Можно ли ехать своим ходом? Ответ в двух строках: можно или нельзя — и что сделать: например, поставить "
    "на дефектовку до выхода в рейс.",
    "uzbek": "Помощник понимает и другие языки — узбекский, таджикский, казахский, киргизский. Спросили на своём "
    "языке — ответ на нём же, цифры и страницы те же.",
    "failed": "Если запись звука плохая, по ней нельзя судить о двигателе. Помощник не ставит диагноз и не создаёт "
    "заявку — просит повторить запись. А посторонние команды в данных проверки он не выполняет.",
    "mismatch": "Если проверка называет неисправность, которой у этого двигателя быть не может, помощник прямо "
    "говорит: такого узла нет — и заявку не создаёт.",
    "contradiction": "В руководствах заказчика мы нашли пять расхождений, а помощник находит новые прямо в работе. "
    "Он не выбирает одно значение молча: показывает обе формулировки и передаёт вопрос главному механику.",
    "passport": "Каждый ответ прозрачен: из каких страниц он собран и сколько он стоил.",
    "chief": "Главный механик видит весь парк: кого ставить на дефектовку первым, у кого растёт оценка, заявки "
    "и противоречия — с готовым письмом заводу. Порядок в списке задают правила, а не нейросеть.",
    "final": "Цифровой механик. Ответы — только по руководству. Решения — за человеком.",
}

OVERLAY_JS = """
(() => {
  if (window.__dm) return;
  const bar = document.createElement('div');
  bar.id = '__dm_sub';
  Object.assign(bar.style, {position: 'fixed', left: '0', right: '0', bottom: '0', zIndex: 2147483647,
    background: 'rgba(0,0,0,0.82)', color: '#fff', font: '600 24px/1.3 system-ui, sans-serif',
    padding: '12px 48px', textAlign: 'center', pointerEvents: 'none', display: 'none'});
  document.documentElement.appendChild(bar);
  const busy = document.createElement('div');
  Object.assign(busy.style, {position: 'fixed', top: '16px', left: '50%', transform: 'translateX(-50%)',
    zIndex: 2147483647, background: 'rgba(0,0,0,0.82)', color: '#fff', font: '600 22px/1.3 system-ui, sans-serif',
    padding: '10px 22px', borderRadius: '10px', pointerEvents: 'none', display: 'none'});
  busy.textContent = 'Агент ищет в руководстве… (ожидание ускорено)';
  document.documentElement.appendChild(busy);
  window.__dm = {
    busy(on) { busy.style.display = on ? 'block' : 'none'; },
    sub(text) { bar.textContent = text; bar.style.display = text ? 'block' : 'none'; },
    mark(el) {
      document.querySelectorAll('[data-dm-mark]').forEach(e => { e.style.outline = e.dataset.dmOld || '';
        e.removeAttribute('data-dm-mark'); });
      if (!el) return;
      el.dataset.dmOld = el.style.outline; el.setAttribute('data-dm-mark', '');
      el.style.outline = '4px solid #f59e0b'; el.style.outlineOffset = '4px';
      el.scrollIntoView({block: 'center', behavior: 'smooth'});
    },
  };
})();
"""


@dataclass
class Take:
    t0: float
    start: float = 0.0  # секунда записи, с которой начинается видео: парк уже на экране (без пустой загрузки)
    waits: list[tuple[float, float]] = field(default_factory=list)  # секунды записи: ожидание ответа модели
    scenes: list[tuple[float, str]] = field(default_factory=list)  # начало сцены (секунды записи) и ключ
    product: list[tuple[float, Path]] = field(default_factory=list)  # озвучка продукта: момент нажатия и файл
    skipped: list[str] = field(default_factory=list)

    def now(self) -> float:
        return time.monotonic() - self.t0


class Director:
    def __init__(
        self,
        page: Any,
        base: str,
        take: Take,
        pace: float = 1.0,
        voice: dict[str, float] | None = None,
        out: Path = ROOT,
    ) -> None:
        self.page, self.base, self.take, self.pace, self.out = page, base, take, pace, out
        self.voice = voice or {}  # ключ сцены → длительность фразы диктора, с
        self.labels: dict[tuple[str, str], str] = {}  # подписи проверок — до записи: запрос к стенду не в кадре

    # ---- подписи, рамка, длина сцены под фразу диктора ----
    def scene(self, key: str) -> None:
        self.fit()
        self.page.evaluate(OVERLAY_JS)
        self.page.evaluate("(t) => window.__dm.sub(t)", NARRATION.get(key, ""))
        self.take.scenes.append((self.take.now(), key))
        print(f"[{self.take.now():6.1f}] {key}: {NARRATION.get(key, '')[:70]}", flush=True)

    def fit(self, extra: float = 0.0) -> None:
        """Текущая сцена — не короче своей фразы: в итоговом видео ожидание модели ускорится (берём худшее — ×8),
        поэтому досчитываем по нему и при нехватке ждём. Фразы не обрезаются и не накладываются."""
        if not self.take.scenes:
            return
        start, key = self.take.scenes[-1]
        need = self.voice.get(key, 0.0) + GAP_S + extra
        now = self.take.now()
        waited = sum(min(b, now) - max(a, start) for a, b in self.take.waits if b > start and a < now)
        final = (now - start) - waited * (1 - 1 / SPEED_MAX)
        if final < need:
            self.page.wait_for_timeout(int((need - final) * 1000))

    def mark(self, locator: Any) -> None:
        self.page.evaluate(OVERLAY_JS)
        if locator is not None and locator.count():
            locator.first.evaluate("(e) => window.__dm.mark(e)")
        else:
            self.page.evaluate("() => window.__dm.mark(null)")

    def pause(self, s: float) -> None:
        """Короткая пауза на анимацию (не больше BEAT_MAX_S): время на чтение кадра даёт фраза диктора (`fit`)."""
        self.page.wait_for_timeout(int(min(s * self.pace, BEAT_MAX_S) * 1000))

    # ---- ожидание модели: только эти куски потом ускоряются ----
    def model_wait(self) -> None:
        start = self.take.now()
        self.page.evaluate(OVERLAY_JS)
        self.page.evaluate("() => window.__dm.busy(true)")
        self.page.wait_for_timeout(800)
        self.page.wait_for_function(f"() => !document.body.innerText.includes({BUSY!r})", timeout=240_000)
        self.page.wait_for_function(
            "() => [...document.querySelectorAll('button')]"
            f".some(b => b.textContent.trim() === {DIAG!r} && !b.disabled)",
            timeout=240_000,
        )
        self.take.waits.append((start, self.take.now()))
        self.page.evaluate(OVERLAY_JS)
        self.page.evaluate("() => window.__dm.busy(false)")
        self.pause(0.6)

    # ---- навигация ----
    def fleet(self) -> None:
        back = self.page.get_by_role("button", name="К парку")
        if back.count() and back.first.is_visible():
            back.first.click()
            self.pause(1.0)

    def vehicle(self, vehicle_id: str, session_id: str | None, new: bool = True) -> None:
        self.fleet()
        self.page.get_by_text(vehicle_id).first.click()
        self.page.get_by_role("radio").first.wait_for(timeout=60_000)  # экран машины открылся
        self.pause(0.8)
        if session_id:
            label = self.labels.get((vehicle_id, session_id)) or session_label(self.base, vehicle_id, session_id)
            radios = self.page.get_by_role("radio")
            for i in range(radios.count()):
                if norm(radios.nth(i).inner_text()).startswith(label):
                    radios.nth(i).click()
                    break
        if not new:
            return
        restart = self.page.get_by_role("button", name="Начать заново")
        button = (
            restart if restart.count() and restart.first.is_visible() else self.page.get_by_role("button", name=DIAG)
        )
        button.first.click()
        self.model_wait()

    def ask(self, question: str) -> None:
        box = self.page.get_by_placeholder("Спросите по руководству")
        box.click()
        box.type(question, delay=35)  # видно, как набирается вопрос
        box.press("Enter")
        self.model_wait()

    def quick(self, text: str) -> bool:
        b = self.page.get_by_role("button", name=text)
        if not b.count():
            self.take.skipped.append(f"быстрый вопрос «{text}»")
            return False
        b.first.click()
        self.model_wait()
        return True

    def listen(self) -> None:
        """«Прослушать»: диктор договорил — нажатие; ответ `/api/voice/speak` (тот же, что слышит механик) ложится
        на момент нажатия; сцена ждёт, пока он прозвучит."""
        play = self.page.get_by_role("button", name=re.compile("Прослушать")).last
        if not play.count():
            self.take.skipped.append("«Прослушать»")
            return
        self.fit()  # диктор договорил: дальше говорит продукт
        play.scroll_into_view_if_needed()
        with self.page.expect_response(lambda r: "/api/voice/speak" in r.url, timeout=60_000) as got:
            clicked = self.take.now()
            play.click()
        resp = got.value
        if resp.status != 200:
            self.take.skipped.append(f"озвучка продукта (HTTP {resp.status})")
            return
        path = self.out / "product-speech.mp3"
        path.write_bytes(resp.body())
        self.take.product.append((clicked, path))
        self.page.wait_for_timeout(int((duration_of(path) + 0.6) * 1000))


def shoot(d: Director) -> None:
    page = d.page
    page.goto(d.base + "/v2", wait_until="domcontentloaded", timeout=120_000)
    page.get_by_text("B418HK98").first.wait_for(timeout=120_000)  # парк на экране — сцена начинается сразу
    page.wait_for_timeout(500)  # список дорисовался
    d.take.start = d.take.now()  # видео — отсюда: загрузка страницы (пустой кадр) в него не входит
    page.evaluate(OVERLAY_JS)
    d.scene("park")
    d.mark(page.get_by_text("B418HK98").first)
    d.pause(3)

    # С1: отклонение → объяснение → страница с рамкой → вопрос → инструмент → заявка → своим ходом (прослушать)
    d.scene("card")
    d.vehicle("B418HK98", "S-0009")
    d.mark(
        page.get_by_text("Отклонение", exact=False).first.locator("xpath=ancestor::*[self::section or self::div][1]")
    )
    d.pause(3)
    chip = page.locator("button:has(svg title)").first
    if chip.count():
        d.scene("page")
        chip.scroll_into_view_if_needed()
        chip.click()
        page.wait_for_timeout(2500)
        d.mark(page.locator("dialog.sheet[open] button span.absolute"))
        d.pause(3)
        d.fit()
        page.locator("dialog.sheet[open]").last.get_by_role("button", name="Закрыть").first.click()
        d.pause(0.6)
    else:
        d.take.skipped.append("чип ✓ в объяснении")

    d.scene("question")
    mic = page.get_by_role("button", name="Сказать вопрос")  # «голосом или текстом»: кнопка микрофона — рамкой
    if mic.count():
        d.mark(mic)
        page.wait_for_timeout(1500)
        d.mark(None)
    d.ask("Какой зазор клапанов?")  # сам вопрос — текстом: звук микрофона не пишем
    d.mark(page.locator("button:has(svg title)").last)
    d.pause(3)

    d.scene("tools")
    if d.quick("Какой нужен инструмент"):
        d.pause(3)

    create = page.get_by_role("button", name="Создать заявку")
    if create.count():
        d.scene("ticket")
        create.first.click()
        d.model_wait()
        opener = page.locator("button", has_text="Открыть заявку")
        if not page.locator("dialog.sheet[open]").count() and opener.count():
            opener.last.click()
            d.pause(1)
        d.pause(3)
        send = page.locator("dialog.sheet[open]").get_by_role("button", name="Отправить в ТОиР")
        if send.count():
            send.first.click()
            page.wait_for_function("() => /Заявка TKT-\\S+ создана/.test(document.body.innerText)", timeout=60_000)
            d.mark(page.get_by_text(re.compile(r"Заявка TKT-\S+ создана")).first)
            d.pause(3)
        else:
            d.take.skipped.append("«Отправить в ТОиР»")
            page.keyboard.press("Escape")
    else:
        d.take.skipped.append("«Создать заявку» (заявка по проверке уже есть — make reset-demo)")

    d.scene("drive")
    if d.quick("Можно ли ехать своим ходом"):
        d.pause(3)
        # «Прослушать» — на коротком ответе (вердикт и одно действие, ≈6–8 с), а не на длинном о зазоре
        d.scene("listen")
        d.listen()

    d.scene("uzbek")
    lang = page.locator("p, label", has_text="Язык ответа").first  # многоязычие: переключатель языка — рамкой
    if lang.count():
        d.mark(lang)
        page.wait_for_timeout(1500)
        d.mark(None)
    d.ask("Klapan tirqishi qancha?")  # короткий вопрос в одну строку
    d.pause(2)
    ru = page.get_by_role("button", name="Показать по-русски")
    if ru.count():
        ru.last.click()
        d.pause(1)
        d.mark(ru.last.locator("xpath=following::*[1]"))
        d.pause(3)
    else:
        d.take.skipped.append("«Показать по-русски»")

    # С3: сбой записи и посторонний текст в ответе ML
    d.scene("failed")
    d.vehicle("H142OX78", "S-0113")
    d.pause(2)
    d.mark(page.get_by_text("посторонний", exact=False).first)
    d.pause(3)

    # С4: несовместимый код
    d.scene("mismatch")
    d.vehicle("M260EH47", "S-0079")
    d.mark(page.get_by_text("не диагноз", exact=False).first)
    d.pause(3)

    # Противоречие в руководствах
    d.scene("contradiction")
    d.vehicle("B418HK98", None, new=False)
    d.ask("Зазоры клапанов регулировать на горячем или на холодном двигателе?")
    d.mark(page.locator('[aria-label="Противоречие в документации"]').last)
    d.pause(4)
    d.scene("passport")
    log = page.locator("details").last
    log.locator("summary").scroll_into_view_if_needed()
    log.locator("summary").click()
    d.pause(1)
    d.mark(log)
    d.pause(3)

    # Главный механик
    d.fit()
    d.fleet()
    chief = page.get_by_role("radio", name="Главный механик")
    if chief.count():
        d.scene("chief")
        chief.first.click()
        d.pause(3)
        queue = page.locator('a[href="#/contradictions"]')
        if queue.count():
            queue.first.click()
            d.pause(2)
            item = page.locator('a[href^="#/contradictions/"]').first
            if item.count():
                item.click()
                d.pause(1.5)
            letter = page.get_by_role("button", name="Письмо")
            if letter.count():
                letter.first.click()
                d.pause(2)
        else:
            d.take.skipped.append("очередь противоречий (нет ссылки)")
    else:
        d.take.skipped.append("режим «Главный механик»")
    d.scene("final")
    d.pause(1)
    d.fit(extra=0.8)


# ---- голос диктора ----
TTS_V3 = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"


def narrate(voice: str, role: str | None, speed: float) -> dict[str, Path]:
    """Фразы диктора — SpeechKit v3, LPCM 48 кГц → WAV (Валерий 27.11: качество — не сжатый поток). Ключ — из
    окружения, в вывод не попадает. Кэш по тексту, голосу, роли и скорости."""
    import base64
    import os
    import wave

    import httpx

    key = (os.environ.get("YANDEX_TTS_API_KEY") or os.environ.get("YANDEX_API_KEY") or "").strip()
    if not key:
        raise SystemExit("нет ключа SpeechKit (YANDEX_TTS_API_KEY) — make video с .env или --silent")
    cache = ROOT / "reports" / "video" / "voice-cache"
    cache.mkdir(parents=True, exist_ok=True)
    http = httpx.Client(timeout=60)
    texts = dict(NARRATION)
    files: dict[str, Path] = {}
    for k, text in texts.items():
        name = hashlib.sha256(f"v3|{voice}|{role}|{speed}|{text}".encode()).hexdigest()[:16]
        path = cache / f"{k}-{name}.wav"
        if not path.exists():
            hints: list[dict[str, Any]] = [{"voice": voice}, {"speed": speed}]
            hints += [{"role": role}] if role else []
            body = {"text": text, "hints": hints, "loudnessNormalizationType": "LUFS",
                    "outputAudioSpec": {"rawAudio": {"audioEncoding": "LINEAR16_PCM",
                                                     "sampleRateHertz": 48000}}}  # fmt: skip
            r = http.post(TTS_V3, json=body, headers={"Authorization": f"Api-Key {key}"})
            pcm = b""
            for line in r.text.splitlines():
                try:
                    chunk = ((json.loads(line).get("result") or {}).get("audioChunk") or {}).get("data")
                except ValueError:
                    continue
                if chunk:
                    pcm += base64.b64decode(chunk)
            if r.status_code != 200 or not pcm:
                raise SystemExit(f"SpeechKit: HTTP {r.status_code} на фразе «{k}»")
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(48000)
                w.writeframes(pcm)
        files[k] = path
    return files


def blank_frames(video: Path, step: float = 0.5) -> list[float]:
    """Пустые кадры (Валерий 27.11: «весь кадр белый»): кадр почти однотонный — разброс яркости меньше 12 из 255.
    Проверяются два кадра в секунду всего ролика; возвращает их время в итоговом видео."""
    cmd = [ffmpeg_exe(), "-i", str(video), "-vf", f"fps={1 / step},signalstats,metadata=mode=print:file=-",
           "-an", "-f", "null", "-"]  # fmt: skip
    out = subprocess.run(cmd, capture_output=True, text=True).stdout  # noqa: S603 — ffmpeg с нашими аргументами
    blank, t, lo = [], 0.0, None
    for line in out.splitlines():
        if m := re.search(r"pts_time:([\d.]+)", line):
            t = float(m.group(1))
        elif m := re.search(r"signalstats\.YMIN=([\d.]+)", line):
            lo = float(m.group(1))
        elif (m := re.search(r"signalstats\.YMAX=([\d.]+)", line)) and lo is not None:
            if float(m.group(1)) - lo < 12:
                blank.append(round(t, 1))
            lo = None
    return blank


# ---- монтаж: только скорость ожидания модели; звук — поверх ----
def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg  # type: ignore[import-not-found]

    return str(imageio_ffmpeg.get_ffmpeg_exe())


def plan(
    duration: float, waits: list[tuple[float, float]], start: float = 0.0
) -> tuple[float, list[tuple[float, float, float]]]:
    """Скорость ожидания (одна на все куски, от ×8 до ×10) и куски записи (начало, конец, скорость) по порядку —
    с секунды `start` (парк на экране) до конца, без вырезов внутри."""
    waits = sorted((max(start, a), min(duration, b)) for a, b in waits if b > max(a, start))
    waited = sum(b - a for a, b in waits)
    rest = duration - start - waited
    speed = SPEED_MIN
    if waited and rest + waited / SPEED_MIN > LIMIT_S:
        speed = min(SPEED_MAX, waited / max(LIMIT_S - rest, 1.0))
    pieces: list[tuple[float, float, float]] = []
    t = start
    for a, b in waits:
        if a > t:
            pieces.append((t, a, 1.0))
        pieces.append((a, b, speed))
        t = b
    if t < duration:
        pieces.append((t, duration, 1.0))
    return speed, pieces


def remap(t: float, pieces: list[tuple[float, float, float]]) -> float:
    out = 0.0
    for a, b, k in pieces:
        if t <= a:
            break
        out += (min(t, b) - a) / k
    return out


def render(src: Path, dst: Path, pieces: list[tuple[float, float, float]]) -> None:
    parts, labels = [], []
    for i, (a, b, k) in enumerate(pieces):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)/{k:.4f}[v{i}]")
        labels.append(f"[v{i}]")
    graph = ";".join(parts) + f";{''.join(labels)}concat=n={len(pieces)}:v=1:a=0[out]"
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-filter_complex", graph, "-map", "[out]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", "-movflags", "+faststart", str(dst)]  # fmt: skip
    subprocess.run(cmd, check=True)  # noqa: S603 — ffmpeg с нашими аргументами


def mix(video: Path, dst: Path, voice: list[tuple[float, Path]], product: list[tuple[float, Path]]) -> None:
    """Звук поверх готового видео (видео копируется как есть): диктор и озвучка продукта (громче), каждая — со своего
    таймкода; нормализация громкости (loudnorm), AAC."""
    inputs, chains, labels = [], [], []
    for i, (t, path) in enumerate([*voice, *product], start=1):
        ms = max(0, int(t * 1000))
        gain = 1.0 if i <= len(voice) else 1.8
        inputs += ["-i", str(path)]
        chains.append(f"[{i}:a]aresample=48000,adelay=delays={ms}:all=1,volume={gain}[a{i}]")
        labels.append(f"[a{i}]")
    graph = ";".join(chains) + (  # лёгкая компрессия, −16 LUFS, истинный пик ≤ −1,5 dBTP — без клиппинга
        f";{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,"
        "acompressor=threshold=-20dB:ratio=2:attack=20:release=250,loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
    )
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(video), *inputs, "-filter_complex", graph,
           "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
           "-movflags", "+faststart", str(dst)]  # fmt: skip
    subprocess.run(cmd, check=True)  # noqa: S603 — ffmpeg с нашими аргументами


def duration_of(path: Path) -> float:
    out = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True).stderr  # noqa: S603
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8010")
    ap.add_argument("--theme", choices=("dark", "light"), default="dark")
    ap.add_argument("--pace", type=float, default=1.6, help="множитель пауз на чтение кадра (1,0 — коротко)")
    ap.add_argument("--narrator", default="anton", help="голос диктора SpeechKit v3 (zahar — голос продукта)")
    ap.add_argument("--role", default="neutral", help="роль голоса v3: neutral, good, …")
    ap.add_argument("--narrator-speed", type=float, default=1.05)
    ap.add_argument("--silent", action="store_true", help="без звука (как первые пробы)")
    ap.add_argument("--label", default=datetime.now().strftime("%Y%m%d-%H%M"))
    args = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    base = args.base.rstrip("/")
    out = ROOT / "reports" / "video" / f"{args.label}-{args.theme}"
    out.mkdir(parents=True, exist_ok=True)
    voice_files = {} if args.silent else narrate(args.narrator, args.role, args.narrator_speed)
    voice_len = {k: duration_of(p) for k, p in voice_files.items()}
    raw = out / "raw"
    labels = {(v, s): session_label(base, v, s) for v, s in DEMO_CHECKS}  # до записи: запрос к серверу не в кадре
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(raw),
            record_video_size={"width": WIDTH, "height": HEIGHT},
        )
        theme = json.dumps(args.theme)  # тема и режим — до загрузки страницы
        ctx.add_init_script(
            "try { localStorage.setItem('dm-theme', " + theme + "); localStorage.setItem('role', 'mechanic') }"
            " catch (e) {}"
        )
        page = ctx.new_page()
        take = Take(t0=time.monotonic())  # запись идёт с создания страницы — отсчёт оттуда же
        director = Director(page, base, take, args.pace, voice_len, out)
        director.labels = labels
        try:
            shoot(director)
        finally:
            video = page.video
            ctx.close()
            browser.close()
        src = Path(video.path()) if video else None
    if src is None or not src.exists():
        print("видео не записалось", file=sys.stderr)
        return 1
    webm = out / "video.webm"
    shutil.move(str(src), webm)
    shutil.rmtree(raw, ignore_errors=True)
    full = duration_of(webm) or take.now()
    speed, pieces = plan(full, take.waits, take.start)
    silent = out / "video-silent.mp4"
    render(webm, silent, pieces)
    mp4 = out / "video.mp4"
    voice_track = [(remap(t, pieces), voice_files[k]) for t, k in take.scenes if k in voice_files]
    product_track = [(remap(t, pieces), p) for t, p in take.product]
    if voice_track or product_track:
        mix(silent, mp4, voice_track, product_track)
    else:
        shutil.copyfile(silent, mp4)
    final = duration_of(mp4)
    waited = sum(b - a for a, b in take.waits)
    lines = [
        f"# Видео — {args.label}, тема {args.theme}",
        "",
        f"Адрес: {base} · исходник {full:.1f} с · ожидание модели {waited:.1f} с, ускорено ×{speed:.1f} · "
        f"итог **{clock(final)}**" + (" ⚠ больше 2:55" if final > LIMIT_S else ""),
        f"Звук: диктор {args.narrator}{f' ({args.role})' if args.role else ''} ×{args.narrator_speed}, v3 WAV 48 кГц"
        + (", озвучка продукта в «Прослушать»" if product_track else "")
        if voice_track
        else "Звук: нет",
        "",
        "| Время | Сцена | Диктор |",
        "|---|---|---|",
        *[f"| {clock(remap(t, pieces))} | {k} | {NARRATION.get(k, '')} |" for t, k in take.scenes],
        *[f"| {clock(remap(t, pieces))} | ▶ озвучка продукта | (голос продукта) |" for t, _ in take.product],
    ]
    blanks = blank_frames(mp4)
    lines += ["", f"Пустые кадры (однотонные, проверка 2 кадра/с): {', '.join(clock(t) for t in blanks) or 'нет'}"]
    if take.skipped:
        lines += ["", "Пропущено (на сервере нет): " + "; ".join(take.skipped)]
    (out / "scenes.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "take.json").write_text(json.dumps({"waits": take.waits, "scenes": take.scenes, "speed": speed,
                                               "product": [(t, str(p)) for t, p in take.product]},
                                              ensure_ascii=False, indent=1), encoding="utf-8")  # fmt: skip
    print("\n".join(lines))
    print(f"\n{mp4.relative_to(ROOT)}")
    return 0 if final <= LIMIT_S and not blanks else 2


if __name__ == "__main__":
    sys.exit(main())
