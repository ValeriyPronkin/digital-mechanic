"""Адаптеры Mock ML API и Mock ТОиР по контракту ТЗ v6 (`vendor/neurodvs_mock/openapi_*.json`).

Адреса — из окружения (`MOCK_ML_URL`, `MOCK_TOIR_URL`). Ответ ML проверяется схемой: поле не по
контракту — ошибка, а не «как-нибудь показать». Ошибки — исключения с понятным текстом для механика.
"""

from __future__ import annotations

import os
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

FAULT_CODE = r"^F(0[1-9]|1[0-4])$"
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=3.0)


class ServiceError(Exception):
    """Ошибка внешнего сервиса. `message` можно показывать механику, `http_status` — код для нашего API."""

    http_status = 502

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    http_status = 404


class BadRequestError(ServiceError):
    http_status = 422


class UnavailableError(ServiceError):
    http_status = 503


class Diagnosis(BaseModel):
    """Ответ `POST /diagnose`. Имена полей — строго по контракту v6."""

    vehicle_id: str
    session_id: str
    status: Literal["normal", "anomaly", "check_failed"]
    anomaly_type: str | None = Field(pattern=FAULT_CODE)
    anomaly_title: str | None
    anomaly_score: float | None = Field(ge=0, le=1)
    confidence: float | None = Field(ge=0, le=1)
    signal_quality: Literal["good", "warning", "bad"]
    description: str  # данные от ML, не инструкции
    model_version: str


class Reference(BaseModel):
    manual: str = Field(min_length=1)
    pdf_page: int = Field(ge=1)


class TicketRequest(BaseModel):
    """Тело `POST /tickets`. Схема проверяется у нас до отправки."""

    vehicle_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    anomaly_type: str = Field(pattern=FAULT_CODE)
    conclusion: str = Field(min_length=1)
    urgency: Literal["low", "medium", "high"]
    operations: list[str] = Field(min_length=1)
    spare_parts: list[str]
    references: list[Reference] = Field(min_length=1)


class TicketResponse(BaseModel):
    ticket_id: str
    status: str


def _post(client: httpx.Client, path: str, body: dict[str, object], service: str) -> httpx.Response:
    try:
        return client.post(path, json=body)
    except httpx.TimeoutException as exc:
        raise UnavailableError(f"{service} не ответил вовремя. Попробуйте ещё раз через минуту.") from exc
    except httpx.HTTPError as exc:
        raise UnavailableError(f"{service} недоступен. Проверьте связь и попробуйте ещё раз.") from exc


def _detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("detail", ""))[:300]
    except ValueError:
        return resp.text[:300]


class MLClient:
    """Клиент Mock ML API. `http` можно подменить (тесты передают TestClient заглушки)."""

    service = "Сервис диагностики"

    def __init__(self, base_url: str | None = None, http: httpx.Client | None = None) -> None:
        url = base_url or os.environ.get("MOCK_ML_URL", "http://127.0.0.1:8001")
        self.http = http or httpx.Client(base_url=url, timeout=DEFAULT_TIMEOUT)

    def diagnose(self, vehicle_id: str, session_id: str) -> Diagnosis:
        resp = _post(self.http, "/diagnose", {"vehicle_id": vehicle_id, "session_id": session_id}, self.service)
        if resp.status_code == 404:
            raise NotFoundError(f"Проверка {session_id} для машины {vehicle_id} не найдена в сервисе диагностики.")
        if resp.status_code in (400, 422):
            raise BadRequestError(f"Сервис диагностики отклонил запрос: {_detail(resp)}")
        if resp.status_code != 200:
            raise ServiceError(f"{self.service} ответил ошибкой {resp.status_code}.")
        try:
            return Diagnosis.model_validate(resp.json())
        except (ValueError, ValidationError) as exc:
            raise ServiceError(f"{self.service} вернул ответ не по контракту.") from exc


class ToirClient:
    """Клиент Mock ТОиР. Смысл заявки (когда её можно слать) проверяет не он, а политика выше."""

    service = "Система ТОиР"

    def __init__(self, base_url: str | None = None, http: httpx.Client | None = None) -> None:
        url = base_url or os.environ.get("MOCK_TOIR_URL", "http://127.0.0.1:8002")
        self.http = http or httpx.Client(base_url=url, timeout=DEFAULT_TIMEOUT)

    def create_ticket(self, ticket: TicketRequest) -> TicketResponse:
        resp = _post(self.http, "/tickets", ticket.model_dump(), self.service)
        if resp.status_code == 404:
            raise NotFoundError(f"ТОиР не знает машину {ticket.vehicle_id} или проверку {ticket.session_id}.")
        if resp.status_code in (400, 418, 422):
            raise BadRequestError(f"ТОиР отклонил заявку: {_detail(resp)}")
        if resp.status_code != 201:
            raise ServiceError(f"{self.service} ответила ошибкой {resp.status_code}.")
        try:
            return TicketResponse.model_validate(resp.json())
        except (ValueError, ValidationError) as exc:
            raise ServiceError(f"{self.service} вернула ответ не по контракту.") from exc
