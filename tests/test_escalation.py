"""Противоречия — эскалация главному механику (Валерий, 27.11): очередь, черновик обращения, отметка «отправлено»,
решение рядом с обеими формулировками, журнал решений; совета «уточните у производителя / специалиста» механику нет."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from service import api_v2, contradictions, main
from service.case_log import verify
from service.clients import MLClient, ToirClient
from service.contradictions import HEADER, check_model_blocks, neutralize
from service.escalation import NO_RULE, ContradictionQueue
from test_agent import make_agent, say
from test_contradictions import QUESTION, RE31, RK269, RK276, Manual236, TorquePages

PASSED = "Передано главному механику на решение (№ 1). Пока — по безопасному правилу выше."


def _agent(ml: MLClient, toir: ToirClient, n: int = 1, search: Any = None, queue: Any = None) -> Any:
    ag, _ = make_agent([say("Можно в течение 15 минут после остановки [R1].")] * n, ml, toir, search or Manual236())
    if queue is not None:
        ag.escalation = queue
    return ag


def test_contradiction_goes_to_queue_instead_of_advice(ml: MLClient, toir: ToirClient) -> None:
    ag = _agent(ml, toir, 2)
    text = ag.ask(ag.start("B418HK98", "S-0007"), QUESTION).text
    assert HEADER in text and PASSED in text
    low = text.lower()
    assert "уточните у" not in low and "специалист" not in low and "производител" not in low  # совета нет
    for quote in (RE31, RK269, RK276):
        assert quote in text
    ag.ask(ag.start("B418HK98", "S-0007"), QUESTION)  # всплыло ещё раз — тот же номер, счётчик +1
    item = ag.escalation.items("open")[0]
    assert item["number"] == 1 and item["count"] == 2 and item["engine"] == "ЯМЗ-236М2"
    assert item["safe_rule"].startswith("Регулировать зазоры на холодном")  # полный текст — в очереди и письме
    assert [f["pdf_page"] for f in item["formulations"]] == [31, 269, 276] and item["vehicles"] == ["B418HK98"]


def test_no_customer_rule_means_rule_from_pages(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Затянуть 430-470 Н·м [R1].")], ml, toir, TorquePages())
    text = ag.ask(ag.start("B418HK98", "S-0007"), "С каким моментом тянуть болты крышек коренных подшипников?").text
    # правило заказчика не нужно: безопасное правило выведено из страниц, эскалация — рядом с ним (ответ 27.11)
    assert "Безопасное правило:" in text and "Пока — по безопасному правилу выше." in text and NO_RULE not in text


def test_letter_send_resolve_and_decision_next_to_both_formulations(ml: MLClient, toir: ToirClient) -> None:
    queue = ContradictionQueue()
    ag = _agent(ml, toir, 2, queue=queue)
    ag.ask(ag.start("B418HK98", "S-0007"), QUESTION)
    letter = queue.letter(queue.get(1), "manufacturer")  # type: ignore[arg-type]
    assert letter.startswith("Кому: завод-изготовитель") and "ЯМЗ-236М2" in letter
    assert RE31 in letter and RK269 in letter and "стр. PDF 31" in letter and "документ-основание" in letter
    sent = queue.send(1, "manufacturer", "главный механик Иванов")
    assert sent["status"] == "sent" and sent["sent"][0]["text"] == letter and sent["sent"][0]["channel"] == "none"
    done = queue.resolve(1, "Регулировать на холодном двигателе (не ранее 15 мин недостаточно)", "главный механик",
                         "manufacturer", "письмо ЯМЗ № 12/345")  # fmt: skip
    assert done["status"] == "resolved"  # type: ignore[index]
    text = ag.ask(ag.start("B418HK98", "S-0007"), QUESTION).text
    assert "Решение по противоречию (№ 1; источник: завод-изготовитель, " in text and "письмо ЯМЗ № 12/345" in text
    assert RE31 in text and RK269 in text and RK276 in text and "Передано главному механику" not in text  # рядом
    journal = queue.journal()
    assert [j["event"] for j in journal] == ["sent", "resolved"] and verify(journal)[0]


def test_cached_answer_shows_todays_decision(ml: MLClient, toir: ToirClient) -> None:
    """Ответ из кэша сохранён до решения — строка эскалации всё равно на сегодня."""
    queue = ContradictionQueue()
    ag = _agent(ml, toir, 1, queue=queue)
    first = ag.ask(ag.start("B418HK98", "S-0007"), QUESTION).text
    queue.resolve(1, "Только на холодном двигателе", "поддержка", "support")
    again = ag.ask(ag.start("B418HK98", "S-0007"), QUESTION)  # второго ответа модели нет — только кэш
    assert "Передано главному механику" in first
    assert "Решение по противоречию (№ 1; источник: поддержка, " in again.text and RK276 in again.text


def test_model_noticed_contradiction_is_queued_and_its_advice_dropped(ml: MLClient, toir: ToirClient) -> None:
    sources = {"R1": "Зазор 0,25 мм на холодном двигателе.", "R2": "Зазор 0,30 мм на прогретом двигателе."}
    text = (
        "Противоречие в документации:\n- «Зазор 0,25 мм на холодном двигателе» [R1]\n"
        "- «Зазор 0,30 мм на прогретом двигателе» [R2]\nСообщите специалисту сервиса о расхождении."
    )
    out, notes = check_model_blocks(text, sources.get, lambda found: f"Передано (№ {len(found)}).")
    assert "Сообщите специалисту" not in out and out.endswith("(№ 2).") and not notes
    # через агента: в очередь по ключу цитат, тот же вопрос — тот же номер
    ag = _agent(ml, toir)
    conv = ag.start("B418HK98", "S-0007")
    r1 = ag._source_for(conv, "yamz-236-re", 31, "Регулировка", RE31).ref
    r2 = ag._source_for(conv, "yamz-236-rk", 269, "Регулировка", RK269).ref
    line = ag._escalate_model(conv, [(RE31, r1), (RK269, r2)])
    assert line == "Передано главному механику на решение (№ 1). Пока — по безопасному правилу выше."
    assert ag._escalate_model(conv, [(RK269, r2), (RE31, r1)]).startswith("Передано главному механику на решение (№ 1)")
    item = ag.escalation.items("open")[0]
    assert item["id"].startswith("model-") and item["count"] == 2
    assert item["safe_rule"] and "дефектовк" in item["safe_rule"]  # правило из страниц, а не «ничего не выбирать»


def test_neutralize_drops_model_advice_lines(ml: MLClient, toir: ToirClient) -> None:
    from service.contradictions import known

    k = known()[0]
    text = (
        "Ответ [R1].\nУточните у производителя двигателя для своей модификации.\n"
        "Для вашей модификации уточните у дилера."
    )
    assert neutralize(k, text) == "Ответ [R1]."


def test_queue_api(ml: MLClient, toir: ToirClient) -> None:
    ag = _agent(ml, toir, 1)
    ag.ask(ag.start("B418HK98", "S-0007"), QUESTION)
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore())
    )
    c = TestClient(app)
    rows = c.get("/api/v2/contradictions?status=open").json()
    assert len(rows) == 1 and rows[0]["number"] == 1 and rows[0]["count"] == 1 and len(rows[0]["formulations"]) == 3
    letter = c.get("/api/v2/contradictions/1/letter?to=support").json()
    assert letter["to"] == "support" and letter["text"].startswith("Кому: поддержка") and letter["channel"] == "none"
    sent = c.post("/api/v2/contradictions/1/send", json={"to": "support", "by": "главный механик"}).json()
    assert sent["status"] == "sent" and c.get("/api/v2/contradictions?status=open").json() == []
    bad = c.post("/api/v2/contradictions/1/resolve", json={"text": "", "by": "x"})
    assert bad.status_code == 422
    done = c.post(
        "/api/v2/contradictions/1/resolve",
        json={"text": "На холодном", "by": "главный механик", "source": "support", "document": "ответ № 7"},
    ).json()
    assert (
        done["resolution"]["document"] == "ответ № 7"
        and c.get("/api/v2/contradictions/1").json()["status"] == "resolved"
    )
    assert [j["event"] for j in c.get("/api/v2/contradictions/journal").json()] == ["sent", "resolved"]
    assert c.get("/api/v2/contradictions/99").status_code == 404
    # весь реестр — у главного механика: всплывшее (№ 1) и известные, о которых ещё не спрашивали
    everything = c.get("/api/v2/contradictions?status=all").json()
    assert len(everything) == len(contradictions.known()) and sorted(r["number"] for r in everything) == list(
        range(1, len(everything) + 1)
    )


def test_block_number_open_and_resolved() -> None:
    """Номер в блоке v2 — и до решения, и после: карточка механика ссылается на тот же № на экране очереди."""
    from service.api_v2 import escalation_view

    open_line = "Передано главному механику на решение (№ 3). Пока — безопасное правило: по выводу выше."
    done_line = "Решение по противоречию (№ 3; источник: завод-изготовитель, 27.11.2026): на холодном двигателе."
    assert escalation_view(open_line) == {"line": open_line, "number": 3, "resolved": False}
    assert escalation_view(done_line) == {"line": done_line, "number": 3, "resolved": True}


def test_whole_registry_known_before_any_question(ml: MLClient, toir: ToirClient) -> None:
    """Валерий 27.11: главный механик видит все известные противоречия сразу — «в ответах 0», номер есть,
    письмо, «отправлено» и решение — без вопроса механика; когда противоречие всплывёт, номер тот же."""
    ag = _agent(ml, toir, 1)
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore())
    )
    c = TestClient(app)
    known = c.get("/api/v2/contradictions?status=known").json()
    assert len(known) == len(contradictions.known()) and all(r["count"] == 0 and r["number"] for r in known)
    assert c.get("/api/v2/contradictions?status=open").json() == []  # никто ещё не спрашивал
    clearance = next(r for r in known if r["id"] == "yamz-236-valve-clearance-timing")
    n = clearance["number"]
    # контракт экрана web-2: не всплывшее — пустые машины и даты, двигатель и формулировки — из реестра
    assert clearance["vehicles"] == [] and clearance["first_seen"] is None and clearance["last_seen"] is None
    assert clearance["engine"] == "ЯМЗ-236М2" and len(clearance["formulations"]) == 3 and clearance["safe_rule"]
    assert {"label", "manual_id", "pdf_page", "quote"} <= set(clearance["formulations"][0])
    letter = c.get(f"/api/v2/contradictions/{n}/letter").json()
    assert "ЯМЗ-236М2" in letter["text"] and "всплывало 0 раз" in letter["text"]
    sent = c.post(f"/api/v2/contradictions/{n}/send", json={"to": "manufacturer", "by": "главный механик"}).json()
    assert sent["status"] == "sent"
    assert len(c.get("/api/v2/contradictions?status=all").json()) == len(known)  # повторно не вносится
    # механик спросил — то же противоречие, тот же номер, «в ответах 1», статус «отправлено» сохранён
    ag.ask(ag.start("B418HK98", "S-0007"), QUESTION)
    row = c.get(f"/api/v2/contradictions/{n}").json()
    assert row["number"] == n and row["count"] == 1 and row["status"] == "sent"


def test_known_becomes_open_when_it_appears(ml: MLClient, toir: ToirClient) -> None:
    ag = _agent(ml, toir, 1)
    app = main.FastAPI()
    app.include_router(
        api_v2.build_router(lambda: ag, lambda: ag.store, main.fleet, lambda r: None, api_v2.ThreadStore())
    )
    c = TestClient(app)
    n = next(r["number"] for r in c.get("/api/v2/contradictions?status=known").json()
             if r["id"] == "yamz-236-valve-clearance-timing")  # fmt: skip
    ag.ask(ag.start("B418HK98", "S-0007"), QUESTION)
    row = c.get(f"/api/v2/contradictions/{n}").json()
    assert row["status"] == "open" and row["count"] == 1 and row["first_seen"]
