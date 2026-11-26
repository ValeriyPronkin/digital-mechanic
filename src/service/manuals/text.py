"""Чистые функции над текстом страниц: склейка переносов, оглавление, номера страниц, нарезка.

Без чтения PDF — тестируются на строках.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# pdfium отдаёт мягкий перенос как U+FFFE: «конди￾ционера». Между цифрами и буквами это настоящий дефис
# («ЛиАЗ￾6212», «ЯМЗ￾238М2»).
_SOFT = "￾"
_SOFT_BREAK = re.compile(r"(?<=[^\W\d_])" + _SOFT + r"[ \t]*\n?[ \t]*(?=[^\W\d_])")
_SOFT_LINE_END = re.compile(_SOFT + r"[ \t]*\n[ \t]*")
# Обычный перенос «слово-\nпродолжение»: только буква-дефис-перевод строки-строчная буква
_HYPHEN_BREAK = re.compile(r"(?<=[а-яёa-z])-[ \t]*\n[ \t]*(?=[а-яёa-z])")
_TRAILING_WS = re.compile(r"[ \t]+\n")
_MULTI_SPACE = re.compile(r"[ \t ]{2,}")
_MULTI_NL = re.compile(r"\n{3,}")


def clean_page_text(raw: str) -> str:
    """Сырой текст страницы → текст для фрагментов: переносы склеены, пробелы нормализованы."""
    s = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    s = _SOFT_BREAK.sub("", s)
    s = _SOFT_LINE_END.sub("-", s)
    s = s.replace(_SOFT, "-")
    s = _HYPHEN_BREAK.sub("", s)
    s = _TRAILING_WS.sub("\n", s)
    s = _MULTI_SPACE.sub(" ", s)
    s = _MULTI_NL.sub("\n\n", s)
    return s.strip()


_PAGE_NO = re.compile(r"\d{1,3}")


def printed_page_number(text: str) -> int | None:
    """Печатный номер страницы — число одной строкой в начале или конце страницы."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for cand in lines[:1] + lines[-1:]:
        if _PAGE_NO.fullmatch(cand):
            return int(cand)
    return None


def detect_page_offset(printed: list[int | None], min_share: float = 0.5) -> int | None:
    """Смещение «печатный номер − номер PDF» (мода). None — номера не напечатаны или смещение не устойчиво.

    printed[i] — печатный номер на странице PDF i+1.
    """
    diffs = Counter(p - (i + 1) for i, p in enumerate(printed) if p is not None)
    if not diffs:
        return None
    offset, count = diffs.most_common(1)[0]
    if count < min_share * sum(1 for p in printed if p is not None):
        return None
    return offset


@dataclass(frozen=True)
class TocEntry:
    title: str
    printed_page: int
    pdf_page: int


_TOC_LINE = re.compile(r"^(?P<title>.*?\S)[\s.…·_]*?\s*(?<![\d,-])(?P<page>\d{1,3})\s*$")
_LEADER = re.compile(r"(?:\s*[.…·_]\s*){2,}$")
_SKIP_TOC = re.compile(r"^(содержание|оглавление|стр\.?)$", re.I)


def parse_toc(lines: list[str], offset: int, n_pages: int) -> list[TocEntry]:
    """Строки страниц оглавления → разделы со страницами PDF.

    Название без номера на конце переносится на следующую строку («Пуск двигателя с помощью
    электрофакельного / устройства (ЭФУ) ... 18»). Печатный номер → PDF: pdf = printed − offset.
    Записи вне документа и выбивающиеся назад больше чем на 30 страниц отбрасываются.
    """
    entries: list[TocEntry] = []
    pending = ""
    for raw in lines:
        line = raw.strip()
        if not line or _SKIP_TOC.match(line):
            continue
        if _PAGE_NO.fullmatch(line):  # колонтитул с номером страницы оглавления
            continue
        m = _TOC_LINE.match(line)
        if not m:
            pending = f"{pending} {line}".strip()
            continue
        title = _LEADER.sub("", m.group("title")).strip(" .…·_")
        title = f"{pending} {title}".strip() if pending else title
        pending = ""
        printed = int(m.group("page"))
        pdf_page = printed - offset
        if not title or not (1 <= pdf_page <= n_pages):
            continue
        if entries and pdf_page < entries[-1].pdf_page - 30:
            continue
        entries.append(TocEntry(title=re.sub(r"\s+", " ", title), printed_page=printed, pdf_page=pdf_page))
    return entries


def section_for_page(toc: list[TocEntry], page: int) -> str:
    """Раздел страницы — последняя запись оглавления, начавшаяся не позже этой страницы."""
    best: TocEntry | None = None
    for e in toc:
        if e.pdf_page <= page and (best is None or e.pdf_page >= best.pdf_page):
            best = e
    return best.title if best else ""


def page_title(text: str) -> str:
    """Первая содержательная строка страницы (заголовок модуля данных в РК ЯМЗ-536)."""
    for ln in text.splitlines():
        s = ln.strip()
        if s and not _PAGE_NO.fullmatch(s):
            return s[:160]
    return ""


def chunk_text(text: str, max_chars: int = 900, overlap_lines: int = 1) -> list[str]:
    """Текст страницы → куски до max_chars по границам строк, с перекрытием в overlap_lines строк."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    for ln in lines:
        while len(ln) > max_chars:  # строка-гигант (таблица без переводов строк)
            cut = ln.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            head, ln = ln[:cut], ln[cut:].lstrip()
            if cur:
                chunks.append("\n".join(cur))
                cur, size = [], 0
            chunks.append(head)
        if cur and size + len(ln) + 1 > max_chars:
            chunks.append("\n".join(cur))
            cur = cur[-overlap_lines:] if overlap_lines else []
            size = sum(len(x) + 1 for x in cur)
        cur.append(ln)
        size += len(ln) + 1
    if cur and (not chunks or "\n".join(cur) not in chunks[-1]):
        chunks.append("\n".join(cur))
    return chunks
