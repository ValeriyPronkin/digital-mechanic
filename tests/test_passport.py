"""Паспорт запроса (#31): поиск, фрагменты «использован / нет», токены и ₽ по шагам, сумма = журнал расходов."""

from __future__ import annotations

import io
import json
import wave
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from service import main, passport
from service.clients import MLClient, ToirClient
from service.store import Store
from test_agent import ANOMALY, TwoPageSearch, make_agent, say

pytestmark = pytest.mark.usefixtures("without_matrix")  # сценарий C1 — как в CI, без матрицы (conftest)


def _ask(ml: MLClient, toir: ToirClient, answer: str) -> tuple[Any, Any, Any]:
    ag, _ = make_agent([say(answer)], ml, toir, TwoPageSearch())  # диагноз и поиск делает код (#16)
    conv = ag.start(*ANOMALY)
    reply = ag.ask(conv, "Какое давление масла?")
    return ag, conv, reply


def test_passport_shows_search_fragments_used_and_cost(ml: MLClient, toir: ToirClient) -> None:
    ag, _, reply = _ask(ml, toir, "На холостом ходу не менее 0,1 МПа [R1]. Затянуть пробку моментом 99 Н·м.")
    pp = passport.build(reply.trace, question="Какое давление масла?", notes=reply.notes)

    names = [t["tool"] for t in pp["tools"]]
    assert names == ["get_diagnosis", "search_manual"] and all(t["by"] == "код" for t in pp["tools"])
    assert all("vehicle_id" not in t["params"] and "session_id" not in t["params"] for t in pp["tools"])

    (search,) = pp["searches"]
    assert search["engine"] and search["found"] == 2 and search["queries"]
    used = {f["pdf_page"]: f["used"] for f in search["fragments"]}
    assert used == {42: True, 77: False}, "неиспользованный контекст помечен"
    assert pp["total"]["unused_tokens"] > 0 and 0 < pp["total"]["unused_share"] < 1

    assert pp["llm"] and pp["llm"][0]["tokens_in"] == 1000 and pp["llm"][0]["tokens_out"] == 200
    journal = sum(c["cost_rub"] for c in ag.store.llm_calls(reply.trace["request_id"]))
    assert pp["total"]["model_rub"] == pytest.approx(journal, abs=1e-4), "сумма сходится с журналом расходов"
    assert sum(x["cost_rub"] for x in pp["llm"]) == pytest.approx(journal, abs=1e-3)
    assert any("цифрами не из руководства: 1" in r for r in pp["rules"])
    assert pp["total"]["total_rub"] >= pp["total"]["model_rub"]


def test_passport_from_answer_cache(ml: MLClient, toir: ToirClient) -> None:
    ag, _ = make_agent([say("Не менее 0,1 МПа [R1].")], ml, toir, TwoPageSearch())
    ag.ask(ag.start(*ANOMALY), "Какое давление масла?")
    again = ag.ask(ag.start(*ANOMALY), "Какое давление масла?")
    pp = passport.build(again.trace, question="Какое давление масла?")
    assert pp["total"]["model_rub"] == 0 and pp["llm"] == []
    assert any("кэша" in r for r in pp["rules"])


def test_redacted_copy_has_no_personal_data(ml: MLClient, toir: ToirClient) -> None:
    _, conv, reply = _ask(ml, toir, "Не менее 0,1 МПа [R1].")
    question = "Какое давление масла? Звоните +7 912 345-67-89"
    pp = passport.redact(passport.build(reply.trace, question=question, notes=reply.notes))
    dump = json.dumps(pp, ensure_ascii=False)
    assert "давление масла" not in dump and "912" not in dump and conv.vehicle.vehicle_id not in dump
    assert pp["searches"][0]["queries"] >= 1 and pp["total"]["model_rub"] > 0  # только число запросов


def test_write_to_bucket_only_by_flag(monkeypatch: pytest.MonkeyPatch, ml: MLClient, toir: ToirClient) -> None:
    _, _, reply = _ask(ml, toir, "Не менее 0,1 МПа [R1].")
    pp = passport.build(reply.trace, question="Какое давление масла?")
    written: list[tuple[str, bytes]] = []
    put = lambda k, b: written.append((k, b))  # noqa: E731
    monkeypatch.delenv("PASSPORT_LOG", raising=False)
    assert passport.write(pp, 1_764_000_000, put) is False and written == []

    monkeypatch.setenv("PASSPORT_LOG", "bucket")
    assert passport.write(pp, 1_764_000_000, None) is False  # журнала стенда нет (локально)
    monkeypatch.setattr(passport.threading, "Thread", _InlineThread)
    assert passport.write(pp, 1_764_000_000, put) is True
    ((key, body),) = written
    assert key == f"logs/2025-11-24/passport/{pp['request_id']}.json"
    assert json.loads(body)["question"]["text"] is None


class _InlineThread:
    def __init__(self, target: Any, **_: Any) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


def _wav(seconds: float = 1.0) -> bytes:
    n = int(seconds * 16_000)
    tone = (3000 * np.sin(np.arange(n) * 2 * np.pi * 220 / 16_000)).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(tone.tobytes())
    return buf.getvalue()


class _FakeSpeech:
    def recognize(self, pcm: bytes, lang: str = "ru") -> str:
        return "какое давление масла"

    def synthesize(self, text: str, api: str = "v1", lang: str = "ru") -> bytes:
        return b"ID3"


def test_api_passport_for_voice_question_and_card(
    ml: MLClient, toir: ToirClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(":memory:")
    ag, _ = make_agent([say("Не менее 0,1 МПа [R1].")], ml, toir, TwoPageSearch())
    monkeypatch.setattr(main, "agent", lambda: ag)
    monkeypatch.setattr(main, "store", lambda: store)
    monkeypatch.setattr(main, "speech", lambda: _FakeSpeech())
    monkeypatch.setattr(main, "ml_client", lambda: ml)
    main.limiter.cache_clear()
    client = TestClient(main.app)
    vid, sid = ANOMALY

    rec = client.post("/api/voice/recognize", content=_wav(3.0)).json()
    assert rec["stt_id"] > 0
    r = client.post(
        "/api/chat",
        json={"vehicle_id": vid, "session_id": sid, "message": rec["text"], "stt_id": rec["stt_id"], "level": "expert"},
    ).json()
    pp = r["passport"]
    assert pp["question"]["level"] == "master"  # прежний «Опытный» (expert) — это «Мастер»
    assert pp["question"]["level_reason"] == "выбран механиком"
    assert pp["question"]["by_voice"] and pp["question"]["stt_seconds"] == pytest.approx(3.0)
    from service.voice import for_tts

    assert pp["voice"]["stt_rub"] > 0 and pp["voice"]["tts_chars"] == len(for_tts(r["speech"]["text"]))
    assert pp["total"]["voice_rub"] == pytest.approx(pp["voice"]["stt_rub"] + pp["voice"]["tts_rub_estimate"], abs=1e-4)

    card = client.post("/api/diagnose", json={"vehicle_id": vid, "session_id": sid}).json()
    cp = card["passport"]
    assert cp["total"]["total_rub"] == 0 and cp["llm"] == [] and cp["tools"][0]["tool"] == "get_diagnosis"
    assert any("модель не вызывалась" in r for r in cp["rules"])


def test_search_refs_without_repeats() -> None:
    """Три фрагмента одной страницы — одна ссылка, в паспорте страница один раз (стенд 27.11: «стр. 276» ×3)."""
    from service.agent import tool_step

    found = [{"ref": "R2"}, {"ref": "R2"}, {"ref": "R3"}, {"ref": "R2"}]
    step = tool_step(0, "search_manual", {"query": "зазор"}, {"found": found, "engine": "ЯМЗ-236М2"}, True, 5)
    assert step["search"]["refs"] == ["R2", "R3"] and step["search"]["found"] == 4
