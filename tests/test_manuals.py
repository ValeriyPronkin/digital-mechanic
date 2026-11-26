"""Индекс руководств без PDF: текст, оглавление, карта двигателей, BM25, слияние и фильтр по двигателю."""

from __future__ import annotations

import numpy as np
import pytest

from service.manuals.catalog import DOCUMENTS, canonical_engine, documents_for_engine
from service.manuals.index import Fragment, fragments_for_document
from service.manuals.lexical import BM25, tokenize
from service.manuals.search import ManualIndex, UnknownEngineError, make_quote, rrf
from service.manuals.text import (
    chunk_text,
    clean_page_text,
    detect_page_offset,
    parse_toc,
    printed_page_number,
    section_for_page,
)

# ---------- текст ----------


def test_soft_hyphen_joins_word_inside_line() -> None:
    assert clean_page_text("компрессора конди￾ционера") == "компрессора кондиционера"


def test_soft_hyphen_at_line_end_joins_word() -> None:
    assert clean_page_text("на холодном ци￾\r\nлиндре") == "на холодном цилиндре"


def test_soft_hyphen_between_letters_and_digits_is_dash() -> None:
    assert clean_page_text("ЛиАЗ￾6212 и ЯМЗ￾238М2") == "ЛиАЗ-6212 и ЯМЗ-238М2"


def test_regular_hyphen_break_joins_only_lowercase() -> None:
    assert clean_page_text("устранить негер-\nметичность") == "устранить негерметичность"
    assert clean_page_text("двигатель ЯМЗ-\n236") == "двигатель ЯМЗ-\n236"


def test_printed_page_number_and_offset() -> None:
    assert printed_page_number("20\r\nМодель двигателя") == 20
    assert printed_page_number("Текст\n\n 21 \n") == 21
    assert printed_page_number("Таблица 3\nТекст") is None
    # РЭ ЯМЗ-536: печатный номер на 1 меньше номера PDF
    printed: list[int | None] = [None, 1, 2, 3, None, 5, 6]
    assert detect_page_offset(printed) == -1
    assert detect_page_offset([None, None]) is None


def test_parse_toc_dot_leaders_and_wrapped_titles() -> None:
    lines = [
        "СОДЕРЖАНИЕ",
        "Стр.",
        "Пуск двигателя с помощью электрофакельного ",
        "устройства (ЭФУ) . . . . . . . . . . . . 18 ",
        "1.1 Назначение двигателей.......................... 10",
        "РЕГУЛИРОВКА ЗАЗОРОВ В КЛАПАННОМ",
        "МЕХАНИЗМЕ 172",
        "Вне документа ........ 999",
    ]
    toc = parse_toc(lines, offset=-1, n_pages=285)
    assert [(e.title, e.printed_page, e.pdf_page) for e in toc] == [
        ("Пуск двигателя с помощью электрофакельного устройства (ЭФУ)", 18, 19),
        ("1.1 Назначение двигателей", 10, 11),
        ("РЕГУЛИРОВКА ЗАЗОРОВ В КЛАПАННОМ МЕХАНИЗМЕ", 172, 173),
    ]
    assert section_for_page(toc, 12) == "1.1 Назначение двигателей"
    assert section_for_page(toc, 200) == "РЕГУЛИРОВКА ЗАЗОРОВ В КЛАПАННОМ МЕХАНИЗМЕ"
    assert section_for_page(toc, 5) == ""


def test_chunk_text_limits_size_and_keeps_all_lines() -> None:
    text = "\n".join(f"строка {i} " + "слово " * 20 for i in range(30))
    chunks = chunk_text(text, max_chars=400)
    assert all(len(c) <= 400 for c in chunks)
    joined = "\n".join(chunks)
    assert all(f"строка {i} " in joined for i in range(30))


# ---------- карта двигателей ----------


def test_engine_map_covers_fleet_engines() -> None:
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).resolve().parents[1] / "data" / "vehicles.json").read_text(encoding="utf-8"))
    for v in data["vehicles"]:
        assert documents_for_engine(v["engine_model"]), v["engine_model"]


@pytest.mark.parametrize(
    ("raw", "canon"),
    [
        ("ЯМЗ-236М2", "ЯМЗ-236М2"),
        ("ямз 236м2", "ЯМЗ-236М2"),
        ("YaMZ", None),
        ("ЯМЗ-236", "ЯМЗ-236М2"),
        ("ЗМЗ-5234", "ЗМЗ-5234.10"),
        ("ЗМЗ – 40904.10", "ЗМЗ-40904.10"),
        ("ЗМЗ-409", None),  # 40904 или 40905 — не угадываем
        ("ЯМЗ-53", None),
        ("ЯМЗ-238", None),
        ("", None),
    ],
)
def test_canonical_engine(raw: str, canon: str | None) -> None:
    assert canonical_engine(raw) == canon


def test_documents_for_engine_never_mixes_makers() -> None:
    assert {d.doc_id for d in documents_for_engine("ЯМЗ-236М2")} == {"yamz-236-re", "yamz-236-rk"}
    assert {d.doc_id for d in documents_for_engine("ЗМЗ-5234.10")} == {"zmz-5234-rk"}
    assert {d.doc_id for d in documents_for_engine("ЗМЗ-40905.10")} == {"zmz-409-rk"}
    assert documents_for_engine("неизвестный") == ()


# ---------- BM25, слияние, цитата ----------


def test_tokenize_lemmatizes_russian() -> None:
    assert tokenize("Тепловые зазоры клапанов") == ["тепловой", "зазор", "клапан"]
    assert "0.25" in tokenize("зазор 0,25 мм")


def test_bm25_ranks_matching_doc_first() -> None:
    docs = [tokenize("замена масла в двигателе"), tokenize("регулировка теплового зазора клапана")]
    scores = BM25(docs).scores(tokenize("зазоры клапанов"), [0, 1])
    assert max(scores, key=lambda i: scores[i]) == 1


def test_rrf_prefers_items_high_in_both_lists() -> None:
    fused = rrf([[1, 2, 3], [3, 1, 4]])
    assert max(fused, key=lambda i: fused[i]) == 1
    assert fused[3] > fused[2]


def test_make_quote_picks_sentence_with_query_words() -> None:
    text = "Общие сведения о двигателе. Зазор на холодном двигателе должен быть 0,25-0,30 мм. Прочее."
    assert "0,25-0,30" in make_quote(text, tokenize("зазор клапана"))


# ---------- фильтр по двигателю в поиске ----------


def _frag(i: int, doc_id: str, text: str) -> Fragment:
    doc = next(d for d in DOCUMENTS if d.doc_id == doc_id)
    return Fragment(
        id=f"{doc_id}:{i}:0",
        doc_id=doc_id,
        designation=doc.designation,
        engines=list(doc.engines),
        kind=doc.kind,
        page=i,
        section="",
        source="текст",
        text=text,
    )


VALVE = "Тепловой зазор клапанов на холодном двигателе {} мм. Регулировка зазора в клапанном механизме."


def _toy_index(vectors: bool = False) -> ManualIndex:
    frags = [
        _frag(1, "yamz-236-re", VALVE.format("0,25-0,30")),
        _frag(2, "yamz-236-rk", "Разборка коленчатого вала"),
        _frag(3, "zmz-5234-rk", VALVE.format("0,20-0,30") + " Тепловой зазор клапанов клапанов."),
        _frag(4, "yamz-536-re", VALVE.format("0,4")),
        _frag(5, "zmz-409-rk", "Гидротолкатели: регулировка зазора не требуется."),
    ]
    if not vectors:
        return ManualIndex(frags)
    # «смысловой» поиск считает лучшим чужой документ — фильтр всё равно не пускает его в выдачу
    vecs = np.eye(len(frags), dtype=np.float32)
    return ManualIndex(frags, vecs, embed_query=lambda q: [0.0, 0.0, 1.0, 0.0, 0.0])


@pytest.mark.parametrize("semantic", [False, True])
def test_search_returns_only_engine_documents(semantic: bool) -> None:
    idx = _toy_index(vectors=semantic)
    hits = idx.search("тепловой зазор клапанов", "ЯМЗ-236М2")
    assert hits
    assert {h.fragment.doc_id for h in hits} <= {"yamz-236-re", "yamz-236-rk"}
    assert hits[0].fragment.doc_id == "yamz-236-re"
    assert "0,25-0,30" in hits[0].quote

    hits = idx.search("тепловой зазор клапанов", "ЗМЗ-5234")
    assert [h.fragment.doc_id for h in hits] == ["zmz-5234-rk"]


def test_search_unknown_engine_raises_not_falls_back() -> None:
    with pytest.raises(UnknownEngineError):
        _toy_index().search("зазор", "КАМАЗ-740")


def test_vectors_must_match_fragments() -> None:
    frags = [_frag(1, "yamz-236-re", "текст")]
    with pytest.raises(ValueError, match="пересоберите"):
        ManualIndex(frags, np.zeros((2, 3), dtype=np.float32))


# ---------- фрагменты документа ----------


def test_fragments_carry_labels_and_ocr_source() -> None:
    doc = next(d for d in DOCUMENTS if d.doc_id == "zmz-409-rk")
    data = {
        "pages": [
            {"page": 1, "raw": "", "text": "Введение. " * 10, "printed": None},
            {"page": 2, "raw": "", "text": "", "printed": None},
            {"page": 120, "raw": "", "text": "Ремонт блока цилиндров. " * 5, "printed": 120},
        ],
        "offset": 0,
        "toc": [{"title": "ВВЕДЕНИЕ", "printed_page": 1, "pdf_page": 1}],
        "tables": [
            {
                "page": 1,
                "tables": [],
                "fault_rows": [{"symptom": "Двигатель не пускается", "cause": "Нет бензина", "remedy": "Залить"}],
            }
        ],
    }
    frags, passport = fragments_for_document(doc, data, {2: "Рисунок 5. Схема"})
    by_source = {f.source for f in frags}
    assert by_source == {"текст", "OCR", "таблица"}
    ocr = next(f for f in frags if f.source == "OCR")
    assert ocr.page == 2 and ocr.text == "Рисунок 5. Схема"
    assert next(f for f in frags if f.page == 120).kind == "ремонт"
    assert next(f for f in frags if f.page == 1).kind == "эксплуатация"
    row = next(f for f in frags if f.source == "таблица")
    assert "Причина: Нет бензина" in row.text and "Способ устранения: Залить" in row.text
    assert all(f.engines == ["ЗМЗ-40904.10", "ЗМЗ-40905.10"] and f.section == "ВВЕДЕНИЕ" for f in frags)
    assert passport["low_text_pages"] == [2] and passport["ocr_pages"] == [2]


def test_engine_name_in_query_does_not_drown_the_answer() -> None:
    """Модель пишет в запрос «ЯМЗ-536», а номер двигателя стоит в колонтитуле каждой страницы РК.
    Двигатель уже отфильтрован — его название из запроса не должно решать, какая страница выше."""
    noise = "Тепловой зазор клапанов: порядок работ. Вывернуть пробку. ЯМЗ-536 ЯМЗ-536 536"
    answer = "Тепловой зазор клапанов: впускных 0,30-0,40 мм, выпускных 0,40-0,50 мм."
    frags = [_frag(i, "yamz-536-rk", noise) for i in range(1, 6)] + [_frag(9, "yamz-536-rk", answer)]
    idx = ManualIndex(frags)
    assert idx.search("тепловой зазор клапанов ЯМЗ-536", "ЯМЗ-536", k=1)[0].fragment.page == 9
