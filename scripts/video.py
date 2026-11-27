"""Видео для жюри одним непрерывным дублем (Валерий, 27.11): Playwright Chromium записывает сессию браузера на
настоящем сервере с настоящей моделью; ускоряется только ожидание ответа модели.

    make video                                   — E2E_URL (по умолчанию make run-local, :8010), тёмная тема
    make video E2E_URL=https://<стенд>/ VIDEO_ARGS="--theme light"

Требования организаторов (27.11): до 3:00, один фрагмент, без монтажа; можно — подписи и стрелки, ускорять только
ожидание ответа модели; показывать только реально работающее. Поэтому:
  • запись — одна сессия браузера, без склеек: ffmpeg только меняет скорость кусков «Готовим ответ…»
    (setpts, равномерно, ×4–8), куски по порядку, ничего не вырезается;
  • подписи — полоска внизу страницы (вставленный элемент поверх экрана), рамка — на ключевом элементе;
  • сцены, которых на сервере нет (кнопки нет), пропускаются и попадают в список пропущенных.
Итог — reports/video/<метка>/video.mp4, исходник video.webm, scenes.md (сцены с таймкодами итогового видео).
Голоса нет (рассказ — на питче): кнопку «Прослушать» не нажимаем.
"""

from __future__ import annotations

import argparse
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
SPEED_MIN, SPEED_MAX = 4.0, 8.0
WIDTH, HEIGHT = 1280, 800

OVERLAY_JS = """
(() => {
  if (window.__dm) return;
  const bar = document.createElement('div');
  bar.id = '__dm_sub';
  Object.assign(bar.style, {position: 'fixed', left: '0', right: '0', bottom: '0', zIndex: 2147483647,
    background: 'rgba(0,0,0,0.82)', color: '#fff', font: '600 26px/1.3 system-ui, sans-serif',
    padding: '14px 28px', textAlign: 'center', pointerEvents: 'none', display: 'none'});
  document.documentElement.appendChild(bar);
  window.__dm = {
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
    waits: list[tuple[float, float]] = field(default_factory=list)  # секунды записи: ожидание ответа модели
    scenes: list[tuple[float, str]] = field(default_factory=list)  # начало сцены и подпись
    skipped: list[str] = field(default_factory=list)

    def now(self) -> float:
        return time.monotonic() - self.t0


class Director:
    def __init__(self, page: Any, base: str, take: Take, pace: float = 1.0) -> None:
        self.page, self.base, self.take, self.pace = page, base, take, pace

    # ---- подписи и рамка ----
    def scene(self, text: str) -> None:
        self.page.evaluate(OVERLAY_JS)
        self.page.evaluate("(t) => window.__dm.sub(t)", text)
        self.take.scenes.append((self.take.now(), text))
        print(f"[{self.take.now():6.1f}] {text}", flush=True)

    def mark(self, locator: Any) -> None:
        self.page.evaluate(OVERLAY_JS)
        if locator is not None and locator.count():
            locator.first.evaluate("(e) => window.__dm.mark(e)")
        else:
            self.page.evaluate("() => window.__dm.mark(null)")

    def pause(self, s: float) -> None:
        """Пауза, чтобы прочитать кадр; `pace` растягивает все паузы разом (длина видео — под 2:40–2:55)."""
        self.page.wait_for_timeout(int(s * self.pace * 1000))

    # ---- ожидание модели: только эти куски потом ускоряются ----
    def model_wait(self) -> None:
        start = self.take.now()
        self.page.wait_for_timeout(800)
        self.page.wait_for_function(f"() => !document.body.innerText.includes({BUSY!r})", timeout=240_000)
        self.page.wait_for_function(
            "() => [...document.querySelectorAll('button')]"
            f".some(b => b.textContent.trim() === {DIAG!r} && !b.disabled)",
            timeout=240_000,
        )
        self.take.waits.append((start, self.take.now()))
        self.page.evaluate(OVERLAY_JS)
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
        self.page.wait_for_load_state("networkidle", timeout=120_000)
        self.pause(0.8)
        if session_id:
            label = session_label(self.base, vehicle_id, session_id)
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


def shoot(d: Director) -> None:
    page = d.page
    page.goto(d.base + "/v2", timeout=120_000)
    page.wait_for_load_state("networkidle", timeout=120_000)
    page.evaluate(OVERLAY_JS)
    d.scene("Парк: 50 машин — сверху те, которыми заняться первыми")
    d.mark(page.get_by_text("B418HK98").first)
    d.pause(4)

    # С1: отклонение → объяснение → страница с рамкой → вопрос → заявка
    d.scene("B418HK98: результат проверки — карточка по правилам кода, модель не нужна")
    d.vehicle("B418HK98", "S-0009")
    d.mark(
        page.get_by_text("Отклонение", exact=False).first.locator("xpath=ancestor::*[self::section or self::div][1]")
    )
    d.pause(4)
    chip = page.locator("button:has(svg title)").first
    if chip.count():
        d.scene("«Как в руководстве»: страница ЯМЗ-236М2, строка с цифрой обведена")
        chip.scroll_into_view_if_needed()
        chip.click()
        page.wait_for_timeout(2500)
        d.mark(page.locator("dialog.sheet[open] button span.absolute"))
        d.pause(5)
        page.locator("dialog.sheet[open]").last.get_by_role("button", name="Закрыть").first.click()
        d.pause(1)
    else:
        d.take.skipped.append("чип ✓ в объяснении")

    d.scene("Вопрос механика: ответ только по руководству этого двигателя, у каждой цифры — страница")
    d.ask("Какой зазор клапанов?")
    d.mark(page.locator("button:has(svg title)").last)
    d.pause(4)

    d.scene("«Какой нужен инструмент» — по руководству, со ссылками")
    if d.quick("Какой нужен инструмент"):
        d.pause(4)

    create = page.get_by_role("button", name="Создать заявку")
    if create.count():
        d.scene("Заявка на дефектовку: работы и запчасти со страницами — механик подтверждает состав")
        create.first.click()
        d.model_wait()
        opener = page.locator("button", has_text="Открыть заявку")
        if not page.locator("dialog.sheet[open]").count() and opener.count():
            opener.last.click()
            d.pause(1)
        d.pause(4)
        send = page.locator("dialog.sheet[open]").get_by_role("button", name="Отправить в ТОиР")
        if send.count():
            send.first.click()
            page.wait_for_function("() => /Заявка TKT-\\S+ создана/.test(document.body.innerText)", timeout=60_000)
            d.scene("Заявка отправлена в ТОиР — номер TKT")
            d.mark(page.get_by_text(re.compile(r"Заявка TKT-\S+ создана")).first)
            d.pause(4)
        else:
            d.take.skipped.append("«Отправить в ТОиР»")
            page.keyboard.press("Escape")
    else:
        d.take.skipped.append("«Создать заявку» (заявка по проверке уже есть — make reset-demo)")

    d.scene("«Можно ли ехать своим ходом» — да/нет словами руководства, со страницей")
    if d.quick("Можно ли ехать своим ходом"):
        d.pause(4)

    d.scene("Вопрос по-узбекски — ответ на языке вопроса, цифры те же, проверены по странице")
    d.ask("Klapan tirqishini qanday tekshirish kerak?")
    d.pause(3)
    ru = page.get_by_role("button", name="Показать по-русски")
    if ru.count():
        ru.last.click()
        d.pause(1)
        d.mark(ru.last.locator("xpath=following::*[1]"))
        d.scene("«Показать по-русски» — обратный перевод для проверки")
        d.pause(4)
    else:
        d.take.skipped.append("«Показать по-русски»")

    # С3: сбой записи и посторонний текст в ответе ML
    d.scene("H142OX78: сбой записи — выводов о двигателе нет, заявки нет")
    d.vehicle("H142OX78", "S-0113")
    d.pause(2)
    d.scene("Текст-подсказка внутри ответа ML показан отдельно и не исполняется")
    d.mark(page.get_by_text("посторонний", exact=False).first)
    d.pause(4)

    # С4: несовместимый код
    d.scene("M260EH47: такого узла у двигателя ЯМЗ-536 нет — проверить повторно, заявки нет")
    d.vehicle("M260EH47", "S-0079")
    d.mark(page.get_by_text("не диагноз", exact=False).first)
    d.pause(5)

    # Противоречие в руководствах
    d.scene("Руководства расходятся: обе формулировки со страницами, решение — за главным механиком")
    d.vehicle("B418HK98", None, new=False)
    d.ask("Зазоры клапанов регулировать на горячем или на холодном двигателе?")
    card = page.locator('[aria-label="Противоречие в документации"]').last
    d.mark(card)
    d.pause(5)
    d.scene("Паспорт ответа: откуда ответ, сколько стоило — в рублях")
    log = page.locator("details").last
    log.locator("summary").scroll_into_view_if_needed()
    log.locator("summary").click()
    d.pause(1)
    d.mark(log)
    d.pause(5)

    # Главный механик
    d.fleet()
    chief = page.get_by_role("radio", name="Главный механик")
    if chief.count():
        d.scene("Главный механик: сводка парка — карантин, требует внимания, норма")
        chief.first.click()
        d.pause(4)
        queue = page.locator('a[href="#/contradictions"]')
        if queue.count():
            d.scene("Противоречия в руководствах: очередь, письмо заводу — по номеру из карточки механика")
            queue.first.click()
            d.pause(3)
            item = page.locator('a[href^="#/contradictions/"]').first
            if item.count():
                item.click()
                d.pause(2)
            letter = page.get_by_role("button", name="Письмо")
            if letter.count():
                letter.first.click()
                d.pause(5)
        else:
            d.take.skipped.append("очередь противоречий (нет ссылки)")
    else:
        d.take.skipped.append("режим «Главный механик»")
    d.scene("")
    d.pause(1)


# ---- монтаж: только скорость ожидания модели ----
def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg  # type: ignore[import-not-found]

    return str(imageio_ffmpeg.get_ffmpeg_exe())


def plan(duration: float, waits: list[tuple[float, float]]) -> tuple[float, list[tuple[float, float, float]]]:
    """Скорость ожидания (одна на все куски, от ×4 до ×8) и куски записи (начало, конец, скорость) по порядку."""
    waits = sorted((max(0.0, a), min(duration, b)) for a, b in waits if b > a)
    waited = sum(b - a for a, b in waits)
    rest = duration - waited
    speed = SPEED_MIN
    if waited and rest + waited / SPEED_MIN > LIMIT_S:
        speed = min(SPEED_MAX, waited / max(LIMIT_S - rest, 1.0))
    pieces: list[tuple[float, float, float]] = []
    t = 0.0
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


def duration_of(path: Path) -> float:
    out = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True).stderr  # noqa: S603
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8010")
    ap.add_argument("--theme", choices=("dark", "light"), default="dark")
    ap.add_argument("--pace", type=float, default=1.6, help="множитель пауз на чтение кадра (1,0 — коротко)")
    ap.add_argument("--label", default=datetime.now().strftime("%Y%m%d-%H%M"))
    args = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    base = args.base.rstrip("/")
    out = ROOT / "reports" / "video" / f"{args.label}-{args.theme}"
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(raw),
            record_video_size={"width": WIDTH, "height": HEIGHT},
        )
        ctx.add_init_script(f"try {{ localStorage.setItem('dm-theme', '{args.theme}'); "
                            "localStorage.setItem('role', 'mechanic') }} catch (e) {{}}")  # fmt: skip
        page = ctx.new_page()
        take = Take(t0=time.monotonic())
        try:
            shoot(Director(page, base, take, args.pace))
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
    speed, pieces = plan(full, take.waits)
    mp4 = out / "video.mp4"
    render(webm, mp4, pieces)
    final = duration_of(mp4)
    waited = sum(b - a for a, b in take.waits)
    lines = [
        f"# Видео — {args.label}, тема {args.theme}",
        "",
        f"Адрес: {base} · исходник {full:.1f} с · ожидание модели {waited:.1f} с, ускорено ×{speed:.1f} · "
        f"итог **{int(final // 60)}:{final % 60:04.1f}**" + (" ⚠ больше 2:55" if final > LIMIT_S else ""),
        "",
        "| Время | Сцена |",
        "|---|---|",
        *[f"| {int(remap(t, pieces) // 60)}:{remap(t, pieces) % 60:04.1f} | {s} |" for t, s in take.scenes if s],
    ]
    if take.skipped:
        lines += ["", "Пропущено (на сервере нет): " + "; ".join(take.skipped)]
    (out / "scenes.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "take.json").write_text(json.dumps({"waits": take.waits, "scenes": take.scenes, "speed": speed},
                                              ensure_ascii=False, indent=1), encoding="utf-8")  # fmt: skip
    print("\n".join(lines))
    print(f"\n{mp4.relative_to(ROOT)}")
    return 0 if final <= LIMIT_S else 2


if __name__ == "__main__":
    sys.exit(main())
