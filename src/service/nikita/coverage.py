# Перенесено из pronkinnikita/digital-mechanic (автор — Никита, pronkinnikita), коммит 2855f726a4,
# с разрешения команды 27.11.2026. Изменены импорты (app.* → наши данные) и текст proof_line; логика — та же.
"""The coverage registry: what this engine's manuals have on each fault type (spec §4.3).

registry/coverage.yaml is data the domain expert signs. It is validated strictly on load: an unknown
field, a fault code outside the fault registry, a page that does not exist or belongs to a manual of
another engine, a `not_covered` cell without its proof or with pages to read: each is an error, not a
silent default. The fault guide tool and the ticket precondition read the registry through `cell_for`.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from service.nikita.manuals import BY_ID, ROOT

Coverage = Literal["covered", "general_inspection_only", "not_covered"]


class _Faults:
    """Коды неисправностей из нашего справочника data/fault_types.json (у Никиты — registry/faults.yaml)."""

    def __init__(self) -> None:
        data = json.loads((ROOT / "data" / "fault_types.json").read_text(encoding="utf-8"))
        self.faults = {f["code"]: f["title"] for f in data}


def load_faults() -> _Faults:
    return _Faults()


REGISTRY_PATH = ROOT / "registry" / "coverage.yaml"
MAX_PAGES = 6


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PageRef(_Strict):
    manual: str
    page: int = Field(ge=1)
    why: str = Field(min_length=1)  # what is on the page, in Russian


class Proof(_Strict):
    text: str = Field(min_length=1)  # the design fact as the mechanic reads it
    manual: str
    page: int = Field(ge=1)


class Cell(_Strict):
    coverage: Coverage = Field(alias="class")
    proof: Proof | None = None
    pages: tuple[PageRef, ...] = Field(default=(), max_length=MAX_PAGES)
    note: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.coverage == "not_covered" and (self.proof is None or self.pages):
            raise ValueError("a not_covered cell needs a proof and lists no pages")
        if self.coverage != "not_covered" and not self.pages:
            raise ValueError("a covered or inspection-only cell lists at least one page")
        places = [(p.manual, p.page) for p in self.pages]
        if len(places) != len(set(places)):
            raise ValueError("a page is listed twice")
        return self


class Engine(_Strict):
    operating_limits: tuple[PageRef, ...] = Field(min_length=1)
    faults: dict[str, Cell]


class Registry(_Strict):
    signed_off_by: str | None
    engines: dict[str, Engine]

    @model_validator(mode="after")
    def _pages_belong_to_the_engine(self) -> Self:
        known_faults = load_faults().faults
        for engine_model, engine in self.engines.items():
            refs = [*engine.operating_limits]
            for code, cell in engine.faults.items():
                if code not in known_faults:
                    raise ValueError(f"{engine_model}: {code} is not a fault type of registry/faults.yaml")
                refs += [*cell.pages, *([cell.proof] if cell.proof else [])]
            for ref in refs:
                manual = BY_ID.get(ref.manual)
                if manual is None or engine_model not in manual.engines:
                    raise ValueError(f"{engine_model}: {ref.manual!r} is not a manual of this engine")
                if ref.page > manual.pages:
                    raise ValueError(f"{engine_model}: {ref.manual} has no page {ref.page}")
        return self


@lru_cache
def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    return Registry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def cell_for(engine_model: str, fault_code: str) -> Cell | None:
    """The registry's decision for this fault on this engine, or None if the pair is not in the registry."""
    engine = load_registry().engines.get(engine_model)
    return engine.faults.get(fault_code) if engine else None


def mismatch(engine_model: str, fault_code: str | None) -> Cell | None:
    """The cell that says this engine cannot have the fault, or None when it can (or the pair is unknown).

    Such a result of a check is an error of the acoustic model, not a diagnosis (the organizers' answer
    of 26 November): the vehicle's card is right about the engine. The cell holds the design fact and the
    page that states it.
    """
    cell = cell_for(engine_model, fault_code) if fault_code else None
    return cell if cell is not None and cell.coverage == "not_covered" else None


def proof_line(cell: Cell) -> str:
    """The design fact with its page in words, for the server's own texts: the card and the recommendation."""
    if cell.proof is None:
        return ""
    return f"{cell.proof.text} ({cell.proof.manual}, стр. {cell.proof.page})"


def limits_for(engine_model: str) -> tuple[PageRef, ...]:
    """Pages with the manual's explicit operating limits and prohibitions for this engine."""
    engine = load_registry().engines.get(engine_model)
    return engine.operating_limits if engine else ()
