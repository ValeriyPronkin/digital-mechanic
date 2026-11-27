"""Ячейки матрицы, которые подписанный инженером реестр покрытия называет покрытыми (registry/coverage.yaml,
V Pronkin, 27.11), а сборка по поиску считала «молчащими»: страницы и работы — из источника, не из поиска.

Стенд 27.11: на F03 × ЯМЗ-236М2 основанием стояла таблица генератора (РЭ стр. 57), на F02 — РЭ стр. 53 без единой
работы, хотя строка «Неисправен манометр — Заменить исправным» на ней есть. Агент говорил «в руководстве нет»."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from build_fault_matrix import ANCHOR_WORDS
from matrix_fixture import needs_matrix
from service.fault_matrix import QUOTE_MAX_WORDS, Ref, normalize, ref_problem

ROOT = Path(__file__).resolve().parents[1]
SRC = json.loads((ROOT / "data" / "fault_matrix.src.json").read_text(encoding="utf-8"))
INDEX = Path(os.environ.get("INDEX_DIR", ".index"))

# (код, группа источника) → (документ, первая страница): первая страница ячейки в реестре покрытия
SIGNED = {
    ("F01", "ЯМЗ-236М2"): ("yamz-236-re", 53),  # B418HK98 S-0009 в видео: «Двигатель стучит» — строка таблицы
    ("F02", "ЯМЗ-236М2"): ("yamz-236-re", 53),
    ("F03", "ЯМЗ-236М2"): ("yamz-236-re", 54),
    ("F04", "ЯМЗ-236М2"): ("yamz-236-re", 28),
    ("F07", "ЯМЗ-236М2"): ("yamz-236-re", 66),
    ("F08", "ЯМЗ-236М2"): ("yamz-236-re", 52),
    ("F04", "ЯМЗ-536"): ("yamz-536-re", 104),
    ("F12", "ЗМЗ-5234.10"): ("zmz-5234-rk", 52),
    ("F13", "ЗМЗ-409"): ("zmz-409-rk", 102),
    # прогон парка 27.11 (S-0100 F04 — без заявки): ещё 6 ячеек, которые реестр разрешает
    ("F01", "ЯМЗ-536"): ("yamz-536-re", 215),
    ("F08", "ЯМЗ-536"): ("yamz-536-re", 191),
    ("F04", "ЗМЗ-5234.10"): ("zmz-5234-rk", 54),  # общий осмотр: одна строка таблицы неисправностей
    ("F05", "ЗМЗ-5234.10"): ("zmz-5234-rk", 57),  # общий осмотр: одна строка таблицы неисправностей
    ("F12", "ЗМЗ-409"): ("zmz-409-rk", 102),
}


def _quotes(o: object) -> list[str]:
    if isinstance(o, dict):
        return [v for k, v in o.items() if k == "quote"] + [q for k, v in o.items() if k != "quote" for q in _quotes(v)]
    if isinstance(o, list):
        return [q for v in o for q in _quotes(v)]
    return []


@pytest.mark.parametrize(("code", "group"), sorted(SIGNED))
def test_signed_cell_lists_registry_pages_and_operations(code: str, group: str) -> None:
    cell = SRC["codes"][code]["cells"][group]
    assert cell["applicable"] == "true" and cell["signed"]
    assert (cell["pages"][0]["doc"], cell["pages"][0]["page"]) == SIGNED[(code, group)]
    assert cell["operations"]  # у общего осмотра — одна строка таблицы неисправностей (организаторы, 26.11)
    for row in cell["operations"] + cell.get("safety", []):
        # в git — только якорь строки, не её текст (#96): не больше 7 слов на строку
        assert "quote" not in row and row["words"] >= len(re.findall(r"\w+", row["anchor"]))
        assert len(re.findall(r"\w+", row["anchor"] + " " + row.get("last", ""))) <= ANCHOR_WORDS
        for engine in SRC["groups"][group]:  # документ — этого двигателя, страница есть в PDF
            assert ref_problem(Ref(doc=row["doc"], page=row["page"], quote=row["anchor"]), engine, None) is None


def test_valve_knock_cites_troubleshooting_page_first_and_works_are_clean() -> None:
    """F01 × ЯМЗ-236М2 (B418HK98 в видео): первая страница и основание — таблица неисправностей РЭ стр. 53 «Двигатель
    стучит → Нарушена регулировка клапанного механизма». Строка оттуда работой не стала: в текстовом слое PDF столбцы
    перемешаны («механи … зма ры»), а работа — строка листа заявки. Работы — РК стр. 269 и РЭ стр. 34."""
    cell = SRC["codes"]["F01"]["cells"]["ЯМЗ-236М2"]
    assert [(p["doc"], p["page"]) for p in cell["pages"]] == [
        ("yamz-236-re", 53),
        ("yamz-236-re", 31),
        ("yamz-236-rk", 229),
        ("yamz-236-rk", 269),
        ("yamz-236-re", 34),
    ]
    ops = [(o["doc"], o["page"]) for o in cell["operations"]]
    assert ops == [("yamz-236-rk", 269), ("yamz-236-re", 34), ("yamz-236-re", 34), ("yamz-236-re", 34)]


F01_WORKS = [
    "Проверить и подрегулировать тепловые зазоры клапанного механизма",
    "Клапанные зазоры рекомендуется регулировать в порядке работы цилиндров",
    "После регулировки зазоров пустить двигатель и прослушать его работу",
    "При появлении стука клапанов остановить двигатель и вновь проверить зазоры",
]


@needs_matrix
def test_valve_knock_ticket_works() -> None:
    """Работы F01 × ЯМЗ-236М2 — строки листа заявки в видео. Без «обкатки» (машина в эксплуатации) и без срока
    «15 мин»: РК стр. 269 («не ранее, чем через 15 мин») и РЭ стр. 31 («или менее чем через 15 минут») расходятся —
    это известное противоречие (data/contradictions.json), ему место в ответе, а не в двух работах заявки."""
    from service.fault_matrix import cell_for

    cell = cell_for("F01", "ЯМЗ-236М2")
    assert cell is not None
    works = [o.quote for o in cell.operations]
    assert works == F01_WORKS
    assert not [w for w in works if "обкатк" in w.lower() or "15 мин" in w]


# Короткие слова, которые бывают в строке руководства; иное слово в 1–3 буквы (не аббревиатура) — обрывок слова,
# разорванного перемешанными столбцами таблицы: «зазо зма ры», «механи … зма».
_SHORT_WORDS = set(
    "и в с со по на не до от из к ко у о об при или его их ее её за мм мин но чем без для под над то же ли а как так "
    "бы оси раз оба что нет вал".split()
)


def interleave_fragments(line: str) -> list[str]:
    return [
        w for w in re.findall(r"[А-Яа-яЁё]+", line) if len(w) <= 3 and not w.isupper() and w.lower() not in _SHORT_WORDS
    ]


def test_fragment_detector_catches_column_interleave() -> None:
    garbled = "Нарушена регулировка клапанного механи Отрегулировать тепловые зазо зма ры в клапанном механизме"
    assert interleave_fragments(garbled) == ["зма", "ры"]
    assert interleave_fragments("Проверить исправность и надежность разъемов ЭБН, пускового реле (ПР) и реле ЭБН") == []


def test_signed_anchors_have_no_word_fragments() -> None:
    for spec in SRC["codes"].values():
        for cell in spec["cells"].values():
            for row in cell.get("operations", []) if "pages" in cell else []:
                assert not interleave_fragments(f"{row['anchor']} {row.get('last', '')}"), row


@needs_matrix
def test_signed_works_read_as_clean_lines() -> None:
    """Работа подписанной ячейки — строка листа заявки: без обрывков слов от перемешанных столбцов PDF."""
    from service.fault_matrix import all_cells

    signed = {
        (code, engine)
        for code, spec in SRC["codes"].items()
        for group, cell in spec["cells"].items()
        if "pages" in cell
        for engine in SRC["groups"][group]
    }
    bad = [
        (c.code, c.engine, o.page, interleave_fragments(o.quote))
        for c in all_cells()
        if (c.code, c.engine) in signed
        for o in c.operations
        if interleave_fragments(o.quote)
    ]
    assert not bad, bad


def test_anchor_expands_to_the_line_on_the_page() -> None:
    """Якорь разворачивается в строку страницы дословно; из двух вхождений начала — то, где строка в `words` слов
    кончается `last` (на стыке фрагментов строка повторяется)."""
    from build_fault_matrix import expand_anchor

    page = "Подтекание по кольцам гильз\nПодтекание по кольцам гильз | Заменить неисправные кольца. Трещины"
    row = {"anchor": "Подтекание по", "last": "неисправные кольца", "words": 7}
    assert expand_anchor(row, page) == "Подтекание по кольцам гильз Заменить неисправные кольца"
    assert expand_anchor({"anchor": "Трещины", "words": 1}, page) == "Трещины"
    assert expand_anchor({"anchor": "Заменить прокладку", "words": 2}, page) is None


def test_source_quotes_stay_short() -> None:
    """Открытый репозиторий (#96): цитата — не длиннее 24 слов подряд, отрывков в файле — не больше 120."""
    quotes = _quotes(SRC)
    assert len(quotes) <= 120
    assert max(len(re.findall(r"\w+", q)) for q in quotes) <= QUOTE_MAX_WORDS


@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_signed_cells_build_confirmed_with_registry_pages() -> None:
    """На собранном индексе: каждая цитата работы — на своей странице, ячейка «подтверждена», первая страница — из
    реестра, ничего не выброшено проверкой."""
    from build_fault_matrix import build

    cells, problems = build(INDEX)
    by = {(c.code, c.engine): c for c in cells}
    for (code, group), first in SIGNED.items():
        for engine in SRC["groups"][group]:
            cell = by[(code, engine)]
            assert cell.status == "confirmed", (code, engine)
            assert (cell.pages[0].doc, cell.pages[0].page) == first
            assert len(cell.operations) == len(SRC["codes"][code]["cells"][group]["operations"])
            assert not [p for p in problems if p.startswith(f"{code} × {engine}:")]


def test_page_quote_starts_at_cell_and_stays_within_words() -> None:
    """Цитата страницы не режет слово («чина Способ…» на стенде 27.11): начало — у ячейки, строки с заглавной или
    предложения рядом с узлом, конец — на границе слова; не длиннее 24 слов; подстрока страницы."""
    from build_fault_matrix import flat, window

    must = re.compile("температур", re.I)
    table = (
        "Таблица 5\nПричина | Способ устранения\nПовышенная температура в системе охлаждения | Заменить термостат. Ещё"
    )
    assert window(table, must) == "Повышенная температура в системе охлаждения Заменить термостат."
    wrapped = "6. При работе следить за\nтемпературой жидкости; " + " ".join(["слово"] * 40)
    quote = window(wrapped, must)
    assert quote.startswith("При работе") and quote in flat(wrapped)  # перенос строки со строчной — не начало
    prose = " ".join(f"слово{i}" for i in range(60)) + " температура " + " ".join(f"хвост{i}" for i in range(60))
    quote = window(prose, must)
    assert quote.startswith("температура ")  # начала ячейки рядом нет — с самого слова узла
    assert len(re.findall(r"\w+", quote)) == QUOTE_MAX_WORDS
    assert all(w in prose.split() for w in quote.split())  # ни одного обрезка слова


def _at_word_bounds(quote: str, page: str) -> bool:
    q = normalize(quote)
    for m in re.finditer(re.escape(q), page):
        before = page[m.start() - 1] if m.start() else " "
        after = page[m.end()] if m.end() < len(page) else " "
        if not re.match(r"\w", before) and not re.match(r"\w", after):
            return True
    return False


@needs_matrix
@pytest.mark.skipif(not (INDEX / "fragments.jsonl").exists(), reason="индекс не собран (make index)")
def test_stored_quotes_do_not_start_or_end_inside_a_word() -> None:
    """Каждая цитата матрицы (основание, страницы, работы, запчасти, предупреждения) на своей странице стоит
    целыми словами: слева и справа от неё на странице — не буква и не цифра."""
    from service.fault_matrix import all_cells
    from service.manuals.index import load_fragments

    texts: dict[tuple[str, int], list[str]] = {}
    for f in load_fragments(INDEX / "fragments.jsonl"):
        texts.setdefault((f.doc_id, f.page), []).append(f.text)
    pages = {k: normalize("\n".join(v)) for k, v in texts.items()}
    bad = [
        (c.code, c.engine, r.page, r.quote[:40])
        for c in all_cells()
        for r in c.refs()
        if not _at_word_bounds(r.quote, pages.get((r.doc, r.page), ""))
    ]
    assert not bad, bad[:10]


def test_cell_without_works_offers_inspection_not_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ячейка без работ: вместо «Черновик заявки — кнопкой «Создать заявку».» — шаг осмотра (заявке нужны работы)."""
    from types import SimpleNamespace

    from service import agent
    from service.fault_matrix import Cell

    card = SimpleNamespace(status="anomaly", compatible=True, fault_code="F07", fault_title="Коробка передач")
    conv = SimpleNamespace(card=card, vehicle=SimpleNamespace(engine_model="ЗМЗ-40904.10"))
    text = "Что проверить\n1. Уровень масла [R1].\n\nЧерновик заявки — кнопкой «Создать заявку»."
    silent = Cell(code="F07", engine="ЗМЗ-40904.10", applicable="true", basis=None, status="silent")
    monkeypatch.setattr(agent, "cell_for", lambda code, engine: silent)
    out = agent.Agent._no_works_step(None, conv, text)  # type: ignore[arg-type]
    assert "Создать заявку" not in out and out.endswith(agent.NO_WORKS_STEP.format(unit="коробка передач"))
    confirmed = Cell(code="F07", engine="ЗМЗ-40904.10", applicable="true", basis=None, status="confirmed",
                     operations=[Ref(doc="zmz-409-rk", page=1, quote="Заменить деталь")])  # fmt: skip
    monkeypatch.setattr(agent, "cell_for", lambda code, engine: confirmed)
    assert agent.Agent._no_works_step(None, conv, text) == text  # работы есть — строка о черновике остаётся
