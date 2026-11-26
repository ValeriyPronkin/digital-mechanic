"""Парк: карточки ТС и история проверок из `data/vehicles.json`, справочник из `data/fault_types.json`.

Модель двигателя берётся только отсюда (в ответе ML её нет). `model` у части машин равно null.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from service.clients import Diagnosis

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))


class Session(Diagnosis):
    """Запись проверки: то же, что ответ /diagnose, плюс время проверки."""

    checked_at: str


class Vehicle(BaseModel):
    vehicle_id: str  # госномер латиницей
    garage_no: str
    make: str
    model: str | None
    vehicle_type: str
    engine_model: str
    fuel: str
    sessions: list[Session]

    @property
    def display_name(self) -> str:
        return f"{self.make} {self.model}" if self.model else self.make


class Fleet(BaseModel):
    vehicles: list[Vehicle]
    fault_titles: dict[str, str]

    def vehicle(self, vehicle_id: str) -> Vehicle | None:
        return next((v for v in self.vehicles if v.vehicle_id == vehicle_id), None)


def load_fleet(data_dir: Path = DATA_DIR) -> Fleet:
    vehicles = json.loads((data_dir / "vehicles.json").read_text(encoding="utf-8"))["vehicles"]
    faults = json.loads((data_dir / "fault_types.json").read_text(encoding="utf-8"))
    return Fleet(vehicles=vehicles, fault_titles={f["code"]: f["title"] for f in faults})


@lru_cache(maxsize=1)
def fleet() -> Fleet:
    return load_fleet()
