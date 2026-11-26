"""Адаптеры ML и ТОиР: контракт v6, понятные ошибки на 404/422, таймаут и недоступность."""

from __future__ import annotations

import httpx
import pytest

from service.clients import (
    BadRequestError,
    MLClient,
    NotFoundError,
    ServiceError,
    TicketRequest,
    ToirClient,
    UnavailableError,
)


def test_diagnose_ok(ml: MLClient) -> None:
    d = ml.diagnose("M333YK47", "S-0005")
    assert d.status == "anomaly" and d.anomaly_type == "F08"


def test_diagnose_404(ml: MLClient) -> None:
    with pytest.raises(NotFoundError, match="не найдена"):
        ml.diagnose("NOPE", "S-0005")
    with pytest.raises(NotFoundError):
        ml.diagnose("M333YK47", "S-0001")  # проверка другой машины


def test_diagnose_422(ml: MLClient) -> None:
    with pytest.raises(BadRequestError):
        ml.diagnose("", "S-0005")


def _mock(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(base_url="http://ml", transport=handler)


def test_timeout_is_unavailable() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(UnavailableError, match="не ответил вовремя"):
        MLClient(http=_mock(httpx.MockTransport(boom))).diagnose("A", "B")


def test_connect_error_is_unavailable() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(UnavailableError, match="недоступен"):
        MLClient(http=_mock(httpx.MockTransport(boom))).diagnose("A", "B")


def test_off_contract_response_rejected() -> None:
    bad = {"vehicle_id": "A", "session_id": "B", "status": "fine"}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=bad))
    with pytest.raises(ServiceError, match="не по контракту"):
        MLClient(http=_mock(transport)).diagnose("A", "B")


def _ticket(**kw: object) -> TicketRequest:
    base: dict[str, object] = {
        "vehicle_id": "M333YK47",
        "session_id": "S-0005",
        "anomaly_type": "F08",
        "conclusion": "Неисправность топливоподачи",
        "urgency": "medium",
        "operations": ["Проверить форсунки"],
        "spare_parts": [],
        "references": [{"manual": "236-3902150-Б РЭ", "pdf_page": 1}],
    }
    base.update(kw)
    return TicketRequest.model_validate(base)


def test_ticket_created(toir: ToirClient) -> None:
    resp = toir.create_ticket(_ticket())
    assert resp.ticket_id.startswith("TKT-") and resp.status == "created"


def test_ticket_404(toir: ToirClient) -> None:
    with pytest.raises(NotFoundError):
        toir.create_ticket(_ticket(session_id="S-9999"))


def test_ticket_schema_checked_before_send() -> None:
    with pytest.raises(ValueError):
        _ticket(operations=[])
    with pytest.raises(ValueError):
        _ticket(references=[{"manual": "x", "pdf_page": 0}])
