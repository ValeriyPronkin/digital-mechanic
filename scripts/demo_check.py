"""Прогон сценария видео на стенде /v2 перед каждым дублем (приём Никиты `make demo-check`, его docs/demo.md).

    make demo-check STAND=https://<стенд>/            — маршрут дубля; заявка доводится до листа, в ТОиР не уходит
    make demo-check ARGS="--backup none"              — без запасной машины
    make demo-check ARGS="--main M739BA198/S-0104"    — дубль на запасной машине
    make demo-check ARGS=--allow-waiting              — «ждёт PR» не мешает коду 0 (дубль без этих PR)
    make demo-check ARGS=--send-ticket                — и отправить заявку (номер TKT и «Создать заявку» до reset-demo)

Делает те же запросы, что телефон (`/`, `/api/v2/fleet`, `/api/v2/chat`, страница, озвучка), по маршруту дубля
(демо-план 27.11): парк → B418HK98 / S-0009: карточка первой, объяснение, первый ✓ → страница с рамкой, вопрос
о зазоре и «Прослушать», «своим ходом», лист заявки со страницей у каждой работы → H142OX78 / S-0113: сбой записи
без выводов и заявки, посторонний текст не «по записи» → тот же маршрут на запасной M739BA198 / S-0104.
Печатает таблицу «шаг → ожидалось → получили → ✅/❌/⏳ → секунды».

Проверка, которой нужен ещё не слитый PR, не падает молча: «⏳ ждёт PR #N» (состояние PR и коммит стенда — из
GitHub API; `GITHUB_TOKEN`, если задан, не печатается). Код возврата: 0 — всё ✅ («готово к дублю»); 1 — есть ❌;
3 — ❌ нет, но есть ⏳ (с `--allow-waiting` — 0); 2 — стенд не ответил.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

STAND = "https://bbab8qkqhuhg3ere9dam.containers.yandexcloud.net/"
REPO = "ValeriyPronkin/digital-mechanic"
DIAG = "Получить результат диагностики"
TICKET = "Создать заявку на дефектовку"  # web/src/copy.ts: thread.createTicketMessage — то, что шлёт кнопка
VALVES = "Какой тепловой зазор клапанов?"
OWN_POWER = "Можно ли ехать своим ходом"  # web/src/copy.ts: быстрый ответ
MAIN = "B418HK98/S-0009"
BACKUP = "M739BA198/S-0104"
FAILED = "H142OX78/S-0113"
MISMATCH = "M260EH47/S-0079"
V2_FIRST_BYTE_S = 3.0  # R4: холодный /v2 — потерянный дубль
BAN = ("не эксплуатировать", "рекомендация, а не запрет")  # T2 / PR #119: карточка без запрета и без его отмены
HANDLE = re.compile(r"\[(S\d+)\]")

# PR, без которых шаг маршрута ещё не может пройти (демо-план 27.11, §2)
PR_ROOT_V2 = 101  # / → /v2/
PR_HEARD = 103  # посторонний текст не в «По записи»
PR_CARD_COPY = 119  # карточка: рекомендация вместо запрета
PR_OP_PAGES = 121  # страница у каждой работы листа заявки (поверх #104)

Status = Literal["ok", "fail", "wait"]
MARK = {"ok": "✅", "fail": "❌", "wait": "⏳"}


@dataclass
class Turn:
    events: list[dict[str, Any]]
    times: list[float]  # секунды от отправки до каждого события
    seconds: float

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("type") == kind]

    def one(self, kind: str) -> dict[str, Any] | None:
        found = self.of(kind)
        return found[-1] if found else None

    def index(self, pred: Callable[[dict[str, Any]], bool]) -> int | None:
        return next((i for i, e in enumerate(self.events) if pred(e)), None)

    @property
    def verdict_at(self) -> int | None:
        return self.index(lambda e: e.get("type") == "tool_result" and (e.get("block") or {}).get("kind") == "verdict")

    @property
    def verdict(self) -> dict[str, Any] | None:
        i = self.verdict_at
        return None if i is None else self.events[i]["block"]

    @property
    def text(self) -> str:
        t = self.one("text")
        return str((t or {}).get("text", ""))

    @property
    def verified(self) -> list[str]:
        return list((self.one("verification") or {}).get("verified") or [])

    @property
    def first_chip(self) -> str | None:
        """Первая метка ✓ в тексте ответа — первый чип с галочкой на экране."""
        ok = set(self.verified)
        return next((h for h in HANDLE.findall(self.text) if h in ok), None)

    @property
    def error(self) -> str | None:
        """Ошибка от сервера, HTTP-код или поток без `done` (обрыв — на экране ответ так и не появится)."""
        e = self.one("error")
        if e:
            return str(e.get("message") or "ошибка")
        return None if self.one("done") else "поток оборван без done"


@dataclass
class Report:
    rows: list[tuple[str, str, str, Status, float | None]] = field(default_factory=list)

    def add(self, step: str, expected: str, got: str, ok: bool | Status, seconds: float | None = None) -> bool:
        status: Status = ok if isinstance(ok, str) else ("ok" if ok else "fail")
        self.rows.append((step, expected, got, status, seconds))
        print(f"{MARK[status]} {step}: {got}" + (f" ({seconds:.1f} с)" if seconds is not None else ""))
        return status == "ok"

    def table(self) -> str:
        out = ["| Шаг | Ожидалось | Получили | | с |", "|---|---|---|---|---|"]
        for step, exp, got, status, sec in self.rows:
            cell = got.replace("|", "/").replace("\n", " ")
            out.append(f"| {step} | {exp} | {cell} | {MARK[status]} | {'' if sec is None else f'{sec:.1f}'} |")
        return "\n".join(out)

    def count(self, status: Status) -> int:
        return sum(1 for r in self.rows if r[3] == status)

    def waiting(self) -> list[str]:
        return sorted({m for r in self.rows if r[3] == "wait" for m in re.findall(r"PR #\d+", r[2])})


class PullRequests:
    """Слит ли PR и есть ли его коммит в сборке стенда (GitHub API, без ключа — 60 запросов в час)."""

    def __init__(
        self, stand_sha: str, enabled: bool = True, repo: str = REPO, transport: httpx.BaseTransport | None = None
    ) -> None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        headers = {"Accept": "application/vnd.github+json"} | ({"Authorization": f"Bearer {token}"} if token else {})
        self.http = httpx.Client(
            base_url=f"https://api.github.com/repos/{repo}", headers=headers, timeout=15, transport=transport
        )
        self.stand_sha, self.enabled = stand_sha, enabled
        self._cache: dict[int, str] = {}

    def state(self, n: int) -> str:
        """open | not-deployed | deployed | unknown"""
        if not self.enabled:
            return "unknown"
        if n not in self._cache:
            self._cache[n] = self._state(n)
        return self._cache[n]

    def _state(self, n: int) -> str:
        try:
            pr = self.http.get(f"/pulls/{n}").json()
            if not pr.get("merged"):
                return "open" if pr.get("state") == "open" else "unknown"
            if not re.fullmatch(r"[0-9a-f]{7,40}", self.stand_sha):
                return "unknown"
            cmp = self.http.get(f"/compare/{pr['merge_commit_sha']}...{self.stand_sha}").json()
            return "deployed" if cmp.get("status") in ("ahead", "identical") else "not-deployed"
        except (httpx.HTTPError, ValueError, KeyError):
            return "unknown"

    def judge(self, ok: bool, n: int) -> tuple[Status, str]:
        """Не прошло — это ждёт PR #n (⏳) или поломка (❌)?"""
        if ok:
            return "ok", ""
        st = self.state(n)
        if st == "open":
            return "wait", f" — ждёт PR #{n}"
        if st == "not-deployed":
            return "wait", f" — PR #{n} слит, стенд собран раньше: Actions → Stand"
        if st == "unknown":
            return "fail", f" (если PR #{n} не слит — ждёт его)"
        return "fail", f" (PR #{n} уже на стенде)"


class Phone:
    """Один «телефон»: своя кука (нить на сервере привязана к браузеру), источники копятся по нити."""

    def __init__(self, base: str, transport: httpx.BaseTransport | None = None) -> None:
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=httpx.Timeout(180, connect=20), follow_redirects=True, transport=transport)
        self.sources: dict[str, dict[str, Any]] = {}
        self.sleep: Callable[[float], None] = time.sleep

    def wait_limit(self, r: httpx.Response) -> None:
        """Стенд пускает 10 вопросов в минуту с одного адреса (`CHAT_RATE_PER_MIN`): ждём, в секунды шага не входит."""
        try:
            wait = min(float(r.headers.get("Retry-After", "30")), 65.0)
        except ValueError:
            wait = 30.0
        print(f"⏸  лимит вопросов стенда в минуту: жду {wait:.0f} с")
        self.sleep(wait)

    def timed_get(self, path: str, **kw: Any) -> tuple[httpx.Response, float]:
        t0 = time.monotonic()
        r = self.http.get(f"{self.base}{path}", **kw)
        return r, time.monotonic() - t0

    def ask(self, vehicle: str, message: str, session: str | None = None, new: bool = False) -> Turn:
        body = {"vehicle_id": vehicle, "message": message, "session_id": session, "new_thread": new, "level": "steps"}
        for attempt in range(3):
            events: list[dict[str, Any]] = []
            times: list[float] = []
            t0 = time.monotonic()
            try:
                with self.http.stream("POST", f"{self.base}/api/v2/chat", json=body) as r:
                    if r.status_code == 429 and attempt < 2:
                        self.wait_limit(r)
                        continue
                    if r.status_code != 200:  # 502 платформы и т. п.: строка ❌, прогон идёт дальше
                        r.read()
                        events.append({"type": "error", "message": f"HTTP {r.status_code}"})
                        times.append(time.monotonic() - t0)
                        break
                    for line in r.iter_lines():
                        if line.startswith("data:"):
                            events.append(json.loads(line[5:].strip()))
                            times.append(time.monotonic() - t0)
            except (httpx.TransportError, ValueError) as exc:  # обрыв посреди потока
                events.append({"type": "error", "message": f"обрыв: {type(exc).__name__}"})
                times.append(time.monotonic() - t0)
            break
        turn = Turn(events, times, time.monotonic() - t0)
        for e in turn.of("sources"):
            for s in e.get("items") or []:
                self.sources[s["handle"]] = s
        return turn

    def page(self, vehicle: str, turn: Turn, h: str) -> tuple[bool, str, float]:
        """Чип → страница: картинка листа и рамка на строке (как «Найдено на странице» в просмотрщике)."""
        s = self.sources.get(h)
        if not s or not s.get("manual_id"):
            return False, f"{h}: нет источника", 0.0
        quotes = (turn.one("verification") or {}).get("quotes") or {}
        t0 = time.monotonic()
        r = self.http.get(
            f"{self.base}/api/v2/vehicles/{vehicle}/pages/{s['manual_id']}/{s['pdf_page']}",
            params={"quote": quotes.get(h) or ""},
        )
        view = r.json() if r.status_code == 200 else {}
        ok = False
        if view.get("image") and view.get("marks"):
            ok = self.http.get(f"{self.base}{view['image']}").status_code == 200
        where = f"{s.get('chip') or s['manual_id']} стр. {s['pdf_page']}"
        what = "картинка и рамка на строке" if ok else ("нет рамки" if view.get("image") else "нет картинки")
        # цитата — и при «нет рамки»: без неё причину не найти (стр. 269, 27.11)
        line = f" «{quotes[h][:60]}»" if quotes.get(h) else " (цитаты для страницы нет)"
        return ok, f"{where}: {what}{line}", time.monotonic() - t0

    def first_page(self, vehicle: str, turn: Turn) -> tuple[bool, str, float]:
        """Первый ✓-чип в тексте должен открыть лист с рамкой; нет — какой следующий открывает (запасной ход)."""
        first = turn.first_chip
        if first is None:
            return False, "чипов с ✓ в тексте нет", 0.0
        ok, got, sec = self.page(vehicle, turn, first)
        if ok:
            return ok, got, sec
        for h in [h for h in dict.fromkeys(HANDLE.findall(turn.text)) if h in set(turn.verified) and h != first]:
            ok2, got2, _ = self.page(vehicle, turn, h)
            if ok2:
                return False, f"{got}; рамка только у следующего: {got2}", sec
        return False, got, sec

    def speak(self, turn: Turn) -> tuple[int, str, float]:
        sp = turn.one("speech")
        if not sp or not sp.get("text"):
            return 0, "нет фразы для озвучки", 0.0
        for attempt in range(3):
            t0 = time.monotonic()
            r = self.http.post(f"{self.base}/api/voice/speak", json={"text": sp["text"], "sig": sp["sig"]})
            sec = time.monotonic() - t0
            if r.status_code != 429 or attempt == 2:
                break
            self.wait_limit(r)
        return r.status_code, f"{r.status_code}, {len(r.content) // 1024} КБ, {r.headers.get('X-TTS', '?')}", sec


def split(spec: str) -> tuple[str, str]:
    car, _, session = spec.partition("/")
    if not car or not session:
        raise SystemExit(f"машина и проверка через «/», например {MAIN}: {spec!r}")
    return car, session


def stand_checks(rep: Report, ph: Phone, github: bool, transport: httpx.BaseTransport | None = None) -> PullRequests:
    """/health; коммит стенда — для «ждёт PR»."""
    r, sec = ph.timed_get("/health")
    try:
        h = r.json()
    except ValueError:
        h = {}
    idx = h.get("manuals_index") or {}
    build = h.get("build") or {}
    ok = (
        r.status_code == 200 and h.get("status") == "ok" and bool(idx.get("present")) and bool(h.get("llm_key_present"))
    )
    got = (
        f"{r.status_code} {h.get('status')}, коммит {build.get('git_sha_short', '—')} "
        f"({build.get('built_at') or 'время сборки —'}), индекс {idx.get('version') or '—'} ({idx.get('fragments')}), "
        f"{h.get('llm_provider')}" + (f", {h['reason']}" if h.get("reason") else "")
    )
    rep.add("Стенд /health", "200 ok, индекс есть, ключ модели есть", got, ok, sec)
    return PullRequests(
        str(build.get("git_sha") or build.get("git_sha_short") or ""), enabled=github, transport=transport
    )


def root_and_fleet(rep: Report, ph: Phone, prs: PullRequests, cars: list[str]) -> None:
    r, sec = ph.timed_get("/", follow_redirects=False)
    loc = r.headers.get("location", "")
    ok = r.status_code in (301, 302, 307, 308) and loc.rstrip("/").endswith("/v2")
    status, note = prs.judge(ok, PR_ROOT_V2)
    rep.add("Адрес стенда /", "переход на /v2/", f"{r.status_code} {loc or 'прежняя страница'}{note}", status, sec)

    r, sec = ph.timed_get("/v2/")
    ok = r.status_code == 200 and sec <= V2_FIRST_BYTE_S
    rep.add("Интерфейс /v2", f"200 не дольше {V2_FIRST_BYTE_S:.0f} с", str(r.status_code), ok, sec)

    r, sec = ph.timed_get("/api/v2/fleet")
    f = r.json() if r.status_code == 200 else {}
    have = {v.get("vehicle_id") for v in f.get("vehicles") or []}
    missing = [c for c in cars if c not in have]
    counts = f.get("counts") or {}
    got = (
        f"машин {len(have)}: карантин {counts.get('quarantine')}, внимание {counts.get('attention')}, "
        f"норма {counts.get('normal')}" + (f"; нет {', '.join(missing)}" if missing else "")
        if f
        else f"HTTP {r.status_code}"
    )
    rep.add("Парк", "50 машин, машины дубля в списке", got, len(have) == 50 and not missing, sec)


def anomaly_route(rep: Report, ph: Phone, prs: PullRequests, spec: str, send_ticket: bool, full: bool) -> None:
    """Маршрут дубля по одной машине: карточка, страница, вопрос, лист заявки. `full` — ещё «своим ходом»."""
    car, session = split(spec)
    r, sec = ph.timed_get(f"/api/v2/vehicles/{car}/tickets")
    sent = [t["ticket_id"] for t in (r.json() if r.status_code == 200 else []) if t.get("session_id") == session]
    rep.add(
        f"{car}: заявки по {session} ещё нет",
        "«Создать заявку» на экране (иначе make reset-demo)",
        f"уже отправлена: {', '.join(sent)}" if sent else ("нет" if r.status_code == 200 else f"HTTP {r.status_code}"),
        r.status_code == 200 and not sent,
        sec,
    )

    t = ph.ask(car, DIAG, session, new=True)
    v = t.verdict or {}
    at = t.verdict_at
    text_at = t.index(lambda e: e.get("type") == "text")
    first = at is not None and (text_at is None or at < text_at)
    got = f"{v.get('case')}: {v.get('headline')}, приоритет {(v.get('urgency') or {}).get('word')}" if v else "нет"
    rep.add(
        f"{car}: карточка первой",
        "отклонение, приоритет; карточка раньше текста (с — до карточки)",
        (got if first else f"{got}; карточка после текста") if v else (t.error or "карточки нет"),
        v.get("case") == "anomaly" and first,
        t.times[at] if at is not None else t.seconds,
    )
    if v:
        words = " ".join([str(v.get("headline") or ""), *map(str, v.get("lines") or [])])
        words += " " + str((v.get("urgency") or {}).get("action") or "")
        hits = [b for b in BAN if b in words.lower()]
        status, note = prs.judge(not hits, PR_CARD_COPY)
        rep.add(f"{car}: карточка без запрета", "нет «не эксплуатировать»", (", ".join(hits) or "нет") + note, status)
    rep.add(
        f"{car}: объяснение",
        "текст со ссылками ✓",
        f"{len(t.text)} знаков, ✓ {len(t.verified)}" + (f", {t.error}" if t.error else ""),
        bool(t.text) and bool(t.verified),
        t.seconds,
    )
    ok, got, sec = ph.first_page(car, t)
    rep.add(f"{car}: первый ✓ → страница", "лист с рамкой на строке", got, ok, sec)

    t = ph.ask(car, VALVES)
    rep.add(
        f"{car}: «{VALVES}»",
        "ответ со ссылкой ✓",
        f"{len(t.text)} знаков, ✓ {len(t.verified)}" + (f", {t.error}" if t.error else ""),
        bool(t.verified),
        t.seconds,
    )
    ok, got, sec = ph.first_page(car, t)
    rep.add(f"{car}: ✓ ответа → страница", "лист с рамкой на строке", got, ok, sec)
    code, got, sec = ph.speak(t)
    rep.add(f"{car}: «Прослушать»", "200, mp3", got, code == 200, sec)

    if full:
        t = ph.ask(car, OWN_POWER)
        low = t.text.lower()
        nothing = any(p in low for p in ("в руководстве нет", "в руководстве этого нет", "прямого указания нет"))
        rep.add(
            f"{car}: «{OWN_POWER}»",
            "ответ по руководству (✓) или «прямого указания нет»",
            f"{len(t.text)} знаков, ✓ {len(t.verified)}"
            + (", «нет в руководстве»" if nothing else "")
            + (f", {t.error}" if t.error else ""),
            bool(t.text) and (bool(t.verified) or nothing),
            t.seconds,
        )

    t = ph.ask(car, TICKET)
    p = t.one("ticket_pending")
    payload = (p or {}).get("payload") or {}
    refs = payload.get("references") or []
    ops = (p or {}).get("operations") or []
    got = (
        f"работ {len(ops)}, ссылок {len(refs)}, приоритет {(p or {}).get('urgency', {}).get('word')}"
        if p
        else f"листа нет{f', {t.error}' if t.error else ''}"
    )
    rep.add(f"{car}: лист заявки", "работы и ссылки, кнопка «Отправить»", got, bool(p and ops and refs), t.seconds)
    if ops:
        bare = [o.get("text", "")[:40] for o in ops if not o.get("pdf_page")]
        status, note = prs.judge(not bare, PR_OP_PAGES)
        pages = ", ".join(
            f"{o.get('short') or o.get('manual') or '?'} стр. {o['pdf_page']}" for o in ops if o.get("pdf_page")
        )
        got = (f"без страницы {len(bare)} из {len(ops)}: «{bare[0]}…»" if bare else pages) + note
        rep.add(f"{car}: страница у каждой работы", "чип «стр. N» под каждой работой", got, status)
    if p and send_ticket:
        r = ph.http.post(
            f"{ph.base}/api/v2/tickets/{p['pending_id']}/approve",
            json={
                "vehicle_id": car,
                "keep_operations": list(range(len(ops))),
                "keep_spare_parts": list(range(len(p.get("spare_parts") or []))),
                "warning_acknowledged": bool(p.get("warning")),
            },
        )
        tid = r.json().get("ticket_id") if r.status_code < 300 else r.text[:120]
        rep.add(f"{car}: отправка в ТОиР", "номер TKT-…", f"{r.status_code} {tid}", r.status_code < 300 and bool(tid))
    elif p:
        rep.add(f"{car}: отправка в ТОиР", "не отправляли (без --send-ticket)", "пропущено — номер не занят", True)


def failed_route(rep: Report, ph: Phone, prs: PullRequests, spec: str) -> None:
    """Сбой записи с посторонним текстом: выводов о двигателе нет, заявки нет, строка не «по записи»."""
    car, session = split(spec)
    t = ph.ask(car, DIAG, session, new=True)
    v = t.verdict or {}
    at = t.verdict_at
    rep.add(
        f"{car}: карточка",
        "сбой записи (серая), без неисправности и приоритета",
        f"{v.get('case')}: {v.get('headline')}" if v else str(t.error),
        v.get("case") == "failed" and not v.get("fault_code") and not v.get("urgency"),
        t.times[at] if at is not None else t.seconds,
    )
    rep.add(f"{car}: без руководства", "ни одного источника", f"источников {len(t.of('sources'))}", not t.of("sources"))
    foreign = str(v.get("foreign_text") or "")
    rep.add(f"{car}: посторонний текст", "отмечен отдельно («Показать»)", foreign[:70] or "нет", bool(foreign))
    if foreign:
        probe = foreign.strip()[:40]
        shown = [
            where for where, s in (("«По записи»", str(v.get("description") or "")), ("ответ", t.text)) if probe in s
        ]
        status, note = prs.judge(not shown, PR_HEARD)
        rep.add(
            f"{car}: строка не «по записи»", "не в описании и не в ответе", (", ".join(shown) or "нет") + note, status
        )
    rep.add(f"{car}: ответ", "без сбоя", t.error or "без сбоя", t.error is None, t.seconds)
    t2 = ph.ask(car, TICKET)
    p = t.one("ticket_pending") is not None or t2.one("ticket_pending") is not None
    got = "лист есть" if p else ("листа нет" + (f", {t2.error}" if t2.error else ""))
    rep.add(f"{car}: заявка при сбое", "листа нет, ответ без сбоя", got, not p and t2.error is None)


def mismatch_route(rep: Report, ph: Phone, spec: str) -> None:
    """Для живых нажатий (не в видео): неисправность узла, которого у двигателя нет."""
    car, session = split(spec)
    t = ph.ask(car, DIAG, session, new=True)
    v = t.verdict or {}
    rep.add(
        f"{car}: карточка",
        "«узла нет»: результат не подходит двигателю",
        f"{v.get('case')}: {v.get('headline')}" if v else str(t.error),
        v.get("case") == "mismatch",
        t.seconds,
    )
    t2 = ph.ask(car, TICKET)
    p = t2.one("ticket_pending")
    got = "лист есть" if p else ("листа нет" + (f", {t2.error}" if t2.error else ""))
    rep.add(f"{car}: заявка при несовместимости", "листа нет, ответ без сбоя", got, not p and t2.error is None)


def run(
    base: str,
    send_ticket: bool,
    main: str = MAIN,
    backup: str | None = BACKUP,
    failed: str = FAILED,
    mismatch: str | None = MISMATCH,
    github: bool = True,
    transport: httpx.BaseTransport | None = None,
) -> Report:
    rep = Report()
    ph = Phone(base, transport)
    prs = stand_checks(rep, ph, github, transport)
    cars = [split(s)[0] for s in (main, backup, failed) if s]
    root_and_fleet(rep, ph, prs, cars)
    anomaly_route(rep, ph, prs, main, send_ticket, full=True)
    failed_route(rep, ph, prs, failed)
    if backup:
        anomaly_route(rep, ph, prs, backup, send_ticket=False, full=False)
    if mismatch:
        mismatch_route(rep, ph, mismatch)
    return rep


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demo_check")
    ap.add_argument("stand", nargs="?", default=STAND)
    ap.add_argument("--main", default=MAIN, help=f"машина/проверка дубля (по умолчанию {MAIN})")
    ap.add_argument("--backup", default=BACKUP, help=f"запасная машина/проверка или none (по умолчанию {BACKUP})")
    ap.add_argument("--failed", default=FAILED, help=f"сбой записи (по умолчанию {FAILED})")
    ap.add_argument("--mismatch", default=MISMATCH, help=f"не тот двигатель или none (по умолчанию {MISMATCH})")
    ap.add_argument("--send-ticket", action="store_true", help="отправить заявку основной машины (займёт номер TKT)")
    ap.add_argument("--allow-waiting", action="store_true", help="⏳ «ждёт PR» не мешает коду 0")
    ap.add_argument("--no-github", action="store_true", help="не спрашивать GitHub о PR (не прошло — значит ❌)")
    ap.add_argument("--out", help="записать таблицу в файл (markdown)")
    args = ap.parse_args(argv)
    none = {"none", "нет", ""}
    t0 = time.monotonic()
    try:
        rep = run(
            args.stand,
            args.send_ticket,
            main=args.main,
            backup=None if args.backup.lower() in none else args.backup,
            failed=args.failed,
            mismatch=None if args.mismatch.lower() in none else args.mismatch,
            github=not args.no_github,
            transport=transport,
        )
    except httpx.HTTPError as exc:
        print(f"❌ стенд не ответил: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    fails, waits = rep.count("fail"), rep.count("wait")
    if fails:
        verdict, code = f"НЕ готово к дублю: ❌ {fails}" + (f", ⏳ {waits}" if waits else ""), 1
    elif waits and not args.allow_waiting:
        verdict, code = f"НЕ готово к дублю: ждёт {', '.join(rep.waiting())}", 3
    elif waits:
        verdict, code = f"готово к дублю без {', '.join(rep.waiting())} (--allow-waiting)", 0
    else:
        verdict, code = "готово к дублю", 0
    total = time.monotonic() - t0
    summary = f"\n{rep.table()}\n\nВесь прогон {total:.0f} с. **{verdict}**"
    print(summary)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(f"# demo-check — {args.stand}\n{summary}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
