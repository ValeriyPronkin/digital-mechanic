"""Сцены видео в браузере (Playwright): телефон (WebKit, iPhone 13 с панелями Safari — 390×664) и ноутбук
(Chromium, 1280×800). Нажимает то же, что механик, и проверяет то, что видно на экране.

    make e2e                                  — локальный сервер (make run-local, порт 8010)
    make e2e E2E_URL=https://<стенд>/         — стенд или превью PR
    make e2e E2E_ARGS="--only phone --send-ticket"
    make e2e E2E_ARGS=--break-images          — картинки страниц не грузятся: лист всё равно со страницей

Сцены (сценарий видео): С1 B418HK98/S-0009 — карточка, вопрос, чип «стр.» → лист страницы в видимой
области с картинкой (или текстом страницы), черновик заявки (с --send-ticket — до номера TKT); противоречие
(тот же ЯМЗ-236М2); паспорт с ₽ в журнале действий; С3 H142OX78/S-0113 — сбой записи, заявки нет;
M260EH47/S-0079 — несовместимый код, заявки нет.
Итог — reports/e2e/<метка>/report.md (таблица «сцена → шаг → ожидалось → получили → ✅/❌») и снимок экрана
на каждый шаг; код 0 — только если всё ✅. Вопросы — свои (не из набора приёмщика); модель настоящая
(≈0,1 ₽ за ответ).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
MONTHS = "янв фев мар апр мая июн июл авг сен окт ноя дек".split()
DIAG = "Получить результат диагностики"
ASK = "Спросите по руководству"
BUSY = "Готовим ответ"
QUESTION = "Какой зазор клапанов?"
CONTRADICTION = "Когда регулировать зазоры клапанов — сразу после остановки можно?"
ANSWER_S = 180  # ответ модели на стенде, с холодным стартом
PROFILES = ("phone", "laptop")


@dataclass
class Row:
    profile: str
    scene: str
    step: str
    expected: str
    got: str
    ok: bool
    shot: str


@dataclass
class Report:
    out: Path
    rows: list[Row] = field(default_factory=list)

    def add(self, page: Any, profile: str, scene: str, step: str, expected: str, got: str, ok: bool) -> bool:
        n = len(self.rows) + 1
        slug = re.sub(r"[^\w]+", "-", f"{scene} {step}".lower()).strip("-")
        shot = f"{n:02d}-{profile}-{slug}.png"
        try:
            page.screenshot(path=str(self.out / shot))
        except Exception:  # снимок не главное: страница могла закрыться
            shot = ""
        self.rows.append(Row(profile, scene, step, expected, got.replace("\n", " ")[:160], ok, shot))
        print(f"{'✅' if ok else '❌'} [{profile}] {scene}: {step} — {got[:100]!r}", flush=True)
        return ok

    def markdown(self, base: str, label: str) -> str:
        bad = sum(not r.ok for r in self.rows)
        head = [
            f"# e2e сцен видео — {label}",
            "",
            f"Адрес: {base} · проверок {len(self.rows)} · не прошло {bad} · "
            + ("**готово к дублю**" if not bad and self.rows else "**есть ❌**"),
            "",
            "| | Профиль | Сцена | Шаг | Ожидалось | Получили | Снимок |",
            "|---|---|---|---|---|---|---|",
        ]
        body = [
            f"| {'✅' if r.ok else '❌'} | {r.profile} | {r.scene} | {r.step} | {r.expected} | "
            f"{r.got.replace('|', '/')} | {f'[png]({r.shot})' if r.shot else '—'} |"
            for r in self.rows
        ]
        return "\n".join(head + body) + "\n"


def session_label(base: str, vehicle_id: str, session_id: str) -> str:
    """Подпись проверки в интерфейсе — «17 ноя»: дата как записана в проверке (web/src/lib/format.ts)."""
    r = httpx.get(f"{base}/api/vehicles/{vehicle_id}", timeout=120)
    r.raise_for_status()
    s = next(x for x in r.json()["sessions"] if x["session_id"] == session_id)
    d = datetime.fromisoformat(s["checked_at"])
    return f"{d.day} {MONTHS[d.month - 1]}"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


class Screen:
    """Экран одного профиля: открыть машину, проверку, спросить, открыть страницу."""

    def __init__(self, page: Any, base: str, phone: bool) -> None:
        self.page, self.base, self.phone = page, base, phone

    def press(self, locator: Any) -> None:
        locator.tap() if self.phone else locator.click()

    def level_question(self) -> None:
        q = self.page.locator('[aria-labelledby="level-q"]')
        if q.count() and q.first.is_visible():
            q.first.locator("button").first.click()
            self.page.wait_for_timeout(300)

    def open_check(self, vehicle_id: str, session_id: str) -> None:
        label = session_label(self.base, vehicle_id, session_id)
        self.page.goto(f"{self.base}/v2", timeout=120_000)
        self.page.wait_for_load_state("networkidle", timeout=120_000)
        self.level_question()
        self.page.get_by_text(vehicle_id).first.click()
        self.page.wait_for_load_state("networkidle", timeout=120_000)  # машина и её прежний разговор загружены
        self.page.wait_for_timeout(500)
        self.level_question()
        radios = self.page.get_by_role("radio")
        for i in range(radios.count()):
            if norm(radios.nth(i).inner_text()).startswith(label):
                radios.nth(i).click()
                break
        # Нить по машине общая: при прежнем разговоре — «Начать заново» (сама просит результат выбранной
        # проверки в новой нити), иначе — «Получить результат диагностики». Не оба: второй запрос — лишний.
        restart = self.page.get_by_role("button", name="Начать заново")
        if restart.count() and restart.first.is_visible():
            restart.first.click()
        else:
            self.page.get_by_role("button", name=DIAG).click()
        self.ready()
        self.idle()

    def idle(self) -> None:
        """Ответ дописан: «Готовим ответ…» пропало (на стенде результат и ответ приходят за секунды)."""
        self.page.wait_for_timeout(800)
        self.page.wait_for_function(f"() => !document.body.innerText.includes({BUSY!r})", timeout=ANSWER_S * 1000)
        self.page.wait_for_timeout(800)

    def ready(self) -> None:
        """Прежний ответ дописан: кнопка «Получить результат диагностики» снова доступна. Карточка приходит
        раньше ответа, а вопрос, отправленный пока ответ пишется, интерфейс не принимает."""
        self.page.wait_for_function(
            "() => [...document.querySelectorAll('button')]"
            f".some(b => b.textContent.trim() === {DIAG!r} && !b.disabled)",
            timeout=ANSWER_S * 1000,
        )

    def logs(self) -> int:
        return int(self.page.locator("details").count())

    def ask(self, question: str) -> float:
        """Вопрос текстом; ответ дописан, когда под ним появился журнал действий."""
        self.ready()
        before, t0 = self.logs(), time.monotonic()
        box = self.page.get_by_placeholder(ASK)
        box.fill(question)
        box.press("Enter")
        self.page.wait_for_function(
            f"() => document.querySelectorAll('details').length > {before}", timeout=ANSWER_S * 1000
        )
        self.idle()
        return time.monotonic() - t0

    def page_sheet(self) -> tuple[bool, str]:
        """Открытый лист страницы: в видимой области, почти на весь экран, с картинкой или текстом страницы."""
        vp = self.page.viewport_size
        sheet = self.page.locator("dialog.sheet[open]").last
        sheet.wait_for(timeout=15_000)
        self.page.wait_for_timeout(400)  # лист выезжает 150 мс: мерить после
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:  # картинка или (после ожидания) текст страницы
            shown = self.page.evaluate(
                """(d) => { const i = d.querySelector('img');
                  const img = i && i.complete && i.naturalWidth > 0 &&
                    getComputedStyle(i.parentElement).visibility !== 'hidden' && i.getBoundingClientRect().height > 50;
                  return {img, text: !!d.querySelector('pre')} }""",
                sheet.element_handle(),
            )
            if shown["img"] or shown["text"]:
                break
            self.page.wait_for_timeout(500)
        box = sheet.bounding_box() or {"y": 0, "height": 0}
        in_view = box["y"] >= 0 and box["y"] + box["height"] <= vp["height"] + 1
        tall = box["height"] >= 0.8 * vp["height"]
        what = "картинка" if shown["img"] else "текст страницы" if shown["text"] else "пусто"
        got = f"лист {box['height']:.0f} из {vp['height']} px, y={box['y']:.0f}; {what}"
        return in_view and tall and what != "пусто", got

    def close_sheet(self) -> None:
        self.page.locator("dialog.sheet[open]").last.get_by_role("button", name="Закрыть").first.click()
        self.page.wait_for_timeout(500)


def scene_s1(scr: Screen, rep: Report, prof: str, send: bool) -> None:
    pg, scene = scr.page, "С1 B418HK98/S-0009"
    scr.open_check("B418HK98", "S-0009")
    ticket_btn = pg.get_by_role("button", name="Создать заявку")
    sent = re.search(r"TKT-\S+", pg.locator("body").inner_text())  # заявка по этой проверке уже отправлена
    rep.add(pg, prof, scene, "карточка", "отклонение: кнопка «Создать заявку» или уже отправленная заявка",
            f"кнопок заявки: {ticket_btn.count()}" + (f"; есть {sent.group(0)}" if sent else ""),
            ticket_btn.count() > 0 or bool(sent))  # fmt: skip
    secs = scr.ask(QUESTION)
    chip = pg.locator("button", has_text="стр.").last
    chips = pg.locator("button", has_text="стр.").count()
    rep.add(
        pg, prof, scene, "ответ на вопрос", "ответ с чипом «стр.»", f"{secs:.0f} с, чипов {chips}", chip.count() > 0
    )
    if chip.count():
        chip.scroll_into_view_if_needed()
        scr.press(chip)
        ok, got = scr.page_sheet()
        rep.add(pg, prof, scene, "чип → страница", "лист в видимой области, ≥ 80 % высоты, страница видна", got, ok)
        scr.close_sheet()
    if ticket_btn.count():
        ticket(scr, rep, prof, scene, ticket_btn, send)
    contradiction_and_passport(scr, rep, prof)


def ticket(scr: Screen, rep: Report, prof: str, scene: str, ticket_btn: Any, send: bool) -> None:
    pg = scr.page
    before = scr.logs()
    scr.press(ticket_btn.first)
    pg.wait_for_function(
        f"() => document.querySelector('dialog.sheet[open]') || document.querySelectorAll('details').length > {before}",
        timeout=ANSWER_S * 1000,
    )
    opener = pg.locator("button", has_text="Открыть заявку")
    if not pg.locator("dialog.sheet[open]").count() and opener.count():
        scr.press(opener.last)
        pg.wait_for_timeout(800)
    sheet = pg.locator("dialog.sheet[open]")
    send_btn = sheet.get_by_role("button", name="Отправить в ТОиР") if sheet.count() else None
    rep.add(pg, prof, scene, "черновик заявки", "лист заявки, кнопка «Отправить в ТОиР»",
            norm(sheet.first.inner_text())[:120] if sheet.count() else "лист не открылся",
            bool(send_btn and send_btn.count()))  # fmt: skip
    if send and send_btn is not None and send_btn.count():
        scr.press(send_btn.first)
        pg.wait_for_function("() => /Заявка TKT-\\S+ создана/.test(document.body.innerText)", timeout=60_000)
        tkt = re.search(r"Заявка (TKT-\S+) создана", pg.locator("body").inner_text())
        rep.add(pg, prof, scene, "отправка в ТОиР", "«Заявка TKT-… создана»", tkt.group(0) if tkt else "нет", bool(tkt))
    elif sheet.count():
        scr.close_sheet()


def contradiction_and_passport(scr: Screen, rep: Report, prof: str) -> None:
    pg = scr.page
    secs = scr.ask(CONTRADICTION)
    card = pg.locator('[aria-label="Противоречие в документации"]')
    if card.count():
        card.last.scroll_into_view_if_needed()
    rep.add(pg, prof, "Противоречие ЯМЗ-236М2", "ответ", "карточка «⚠ Противоречие в документации»",
            f"{secs:.0f} с, карточек {card.count()}", card.count() > 0)  # fmt: skip

    log = pg.locator("details").last
    log.locator("summary").scroll_into_view_if_needed()
    summary = norm(log.locator("summary").inner_text())
    log.locator("summary").click()
    pg.wait_for_timeout(500)
    body = norm(log.inner_text())
    got = f"{summary[:80]} · {len(body)} знаков"
    ok = "₽" in summary and len(body) > len(summary)
    rep.add(pg, prof, "Паспорт ₽", "журнал действий", "строка с ₽, паспорт раскрывается", got, ok)


def scene_no_ticket(
    scr: Screen, rep: Report, prof: str, vid: str, sid: str, scene: str, words: tuple[str, ...]
) -> None:
    pg = scr.page
    scr.open_check(vid, sid)
    text = norm(
        pg.locator("main").first.inner_text() if pg.locator("main").count() else pg.locator("body").inner_text()
    )
    found = [w for w in words if w in text.lower()]
    tickets = pg.get_by_role("button", name="Создать заявку").count()
    rep.add(pg, prof, scene, "карточка", f"без заявки; есть «{' / '.join(words)}»",
            f"кнопок заявки {tickets}; найдено {found or 'ничего'}", tickets == 0 and bool(found))  # fmt: skip


def run_profile(pw: Any, prof: str, base: str, rep: Report, send: bool, break_images: bool = False) -> None:
    phone = prof == "phone"
    browser = pw.webkit.launch() if phone else pw.chromium.launch()
    try:
        ctx_args = {**pw.devices["iPhone 13"], "viewport": {"width": 390, "height": 664}} if phone else {
            "viewport": {"width": 1280, "height": 800}
        }  # fmt: skip
        failed_words = ("непригодн", "повтор")
        mismatch_words = ("не диагноз", "нет у", "несовмест")
        scenes: list[Callable[[Screen], None]] = [
            lambda s: scene_s1(s, rep, prof, send),
            lambda s: scene_no_ticket(s, rep, prof, "H142OX78", "S-0113", "С3 H142OX78/S-0113", failed_words),
            lambda s: scene_no_ticket(s, rep, prof, "M260EH47", "S-0079", "M260EH47/S-0079", mismatch_words),
        ]
        for scene in scenes:
            ctx = browser.new_context(**ctx_args)
            page = ctx.new_page()
            if break_images:  # iPhone 27.11: картинка не пришла — лист был только шапкой и кнопками
                page.route("**/manuals/**/page/*", lambda route: route.abort())
            try:
                scene(Screen(page, base, phone))
            except Exception as exc:  # сцена упала — строка ❌ со снимком, остальные идут дальше
                rep.add(page, prof, "сцена", "прервана", "без ошибок", f"{type(exc).__name__}: {str(exc)[:120]}", False)
            finally:
                ctx.close()
    finally:
        browser.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8010")
    ap.add_argument("--only", choices=PROFILES)
    ap.add_argument("--send-ticket", action="store_true", help="довести заявку до номера TKT (займёт номер в ТОиР)")
    ap.add_argument("--break-images", action="store_true", help="отказ на картинки страниц (проверка запасного вида)")
    ap.add_argument("--label", default=datetime.now().strftime("%Y%m%d-%H%M"))
    args = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    base = args.base.rstrip("/")
    out = ROOT / "reports" / "e2e" / args.label
    out.mkdir(parents=True, exist_ok=True)
    rep = Report(out)
    with sync_playwright() as pw:
        for prof in [args.only] if args.only else PROFILES:
            run_profile(pw, prof, base, rep, args.send_ticket, args.break_images)
    (out / "report.md").write_text(rep.markdown(base, args.label), encoding="utf-8")
    bad = sum(not r.ok for r in rep.rows)
    print(f"\n{out.relative_to(ROOT)}/report.md — проверок {len(rep.rows)}, не прошло {bad}")
    return 0 if rep.rows and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
