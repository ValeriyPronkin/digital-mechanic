"""Снятое утверждение видно на своём месте (инвариант: сбой проверки — «не подтверждено», а не «в руководстве нет»).

Раньше guard молча удалял фразу: в событии verification было `"withdrawn": []`, в заметках — «не нашёл в
руководстве», нумерация шагов шла с пропуском («1. / 3. / 4.»). Теперь на месте фразы — пометка, которую интерфейс v2
читает (`web/src/lib/answer.ts`: WITHDRAWN, attachWithdrawn), а событие перечисляет снятые утверждения в том же порядке
в форме `WithdrawnClaim` из `web/src/api.ts`: {text, state, missing, reason, handles}."""

from __future__ import annotations

import re

from service import api_v2
from service.agent import WITHDRAWN_UNCITED, WITHDRAWN_UNVERIFIED, Source
from service.clients import MLClient, ToirClient
from test_agent import ANOMALY, make_agent, say

# как web/src/lib/answer.ts строит WITHDRAWN из copy.thread.withdrawn / withdrawnTail
WEB_NOTE = re.compile(r"(Утверждение снято:[^.]*\.(?: Сверьте со страницей\.?)?)")
PAGE = "Давление масла на прогретом двигателе 0,4–0,7 МПа. Пробку сливного отверстия затянуть."


class OnePage:
    available = True

    def search(self, query: str, engine: str, k: int = 5) -> list:  # type: ignore[type-arg]
        from service.manual_search import ManualHit

        return [ManualHit("yamz-236-re", "РЭ", 42, "Смазка", PAGE)]

    def page_text(self, manual_id: str, pdf_page: int) -> str | None:
        return PAGE if (manual_id, pdf_page) == ("yamz-236-re", 42) else None


ANSWER = (
    "Давление масла 0,4–0,7 МПа [R1].\n\n"
    "1. Прогрейте двигатель [R1].\n"
    "2. Затяните пробку моментом 45 Н·м [R1].\n"
    "3. Проверьте давление по указателю [R1].\n"
    "Ресурс фильтра 15 000 км."
)


def _reply(ml: MLClient, toir: ToirClient):  # type: ignore[no-untyped-def]
    ag, _ = make_agent([say(ANSWER)], ml, toir, OnePage())
    return ag.ask(ag.start(*ANOMALY), "Какое давление масла?")


def test_withdrawn_claim_is_replaced_in_place_and_numbering_kept(ml: MLClient, toir: ToirClient) -> None:
    reply = _reply(ml, toir)
    text = reply.text
    assert "45" not in text and "15 000" not in text  # не подтверждено — числа нет
    assert f"2. {WITHDRAWN_UNVERIFIED} [R1]" in text  # на своём месте, со ссылкой, которую называло
    assert "1. Прогрейте двигатель [R1].\n2. " in text and "\n3. Проверьте давление" in text  # без пропуска
    assert WITHDRAWN_UNCITED in text  # число без ссылки — снято с пометкой «не указана страница»
    assert "не нашёл" not in text and not any("не нашёл" in n for n in reply.notes)


def test_verification_event_lists_withdrawn_claims_in_note_order(ml: MLClient, toir: ToirClient) -> None:
    reply = _reply(ml, toir)
    text = api_v2.to_handles(reply.text)
    ver = api_v2.verification(reply, text)
    notes = WEB_NOTE.findall(text)
    assert len(notes) == len(ver["withdrawn"]) == 2  # интерфейс сопоставляет пометку и утверждение один к одному
    first, second = ver["withdrawn"]
    assert first == {
        "text": "Затяните пробку моментом 45 Н·м [S1].",
        "state": "unverified",
        "missing": ["45"],
        "reason": "not_on_page",
        "handles": ["S1"],
    }
    assert second["state"] == "uncited" and second["reason"] == "no_source" and second["handles"] == []
    assert ver["counts"]["unverified"] == 1 and ver["counts"]["uncited"] == 1
    assert ver["verified"] == ["S1"] and "0,4–0,7" in ver["quotes"]["S1"]  # ✓ — только по найденному числу


def test_number_from_another_table_row_is_withdrawn_with_its_reason(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([], ml, toir)
    conv = ag.start(*ANOMALY)
    conv.sources["R1"] = Source(ref="R1", manual_id="yamz-236-rk", manual="РК", pdf_page=286, section="",
                                text="Болты крепления маховика 200-220\nГайки распылителей форсунок 60-80")  # fmt: skip
    conv.messages.append({"role": "user", "content": "Какой момент затяжки гаек распылителей?"})
    text, *_ = ag.guard(conv, "Гайки распылителей затянуть 200-220 Н·м [R1].")
    assert "200-220" not in text and "другой строке таблицы. Сверьте со страницей. [R1]" in text
    assert conv.withdrawn[0]["reason"] == "other_row"
