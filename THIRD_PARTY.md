# Сторонние компоненты

Положение, п. 4.4, 4.8, 9.1. Раздел «Python-зависимости» CI сверяет с `pyproject.toml`
(`scripts/check_third_party.py`): прямые зависимости, лицензия — из метаданных пакета.
Транзитивные зависимости и точные версии — в `uv.lock`.

## Python-зависимости

| Пакет | Версия | Лицензия | Зачем |
|---|---|---|---|
| fastapi | >=0.115 | MIT | HTTP API и страница |
| uvicorn | >=0.30 | BSD-3-Clause | ASGI-сервер |
| httpx | >=0.28.1 | BSD-3-Clause | HTTP-клиент: Mock ML и Mock ТОиР, Yandex OCR и эмбеддинги; тестовый клиент FastAPI |
| pydantic | >=2.7 | MIT | схемы ответов ML и заявки ТОиР по контракту v6 |
| mypy | >=1.11 | MIT | dev: проверка типов |
| pytest | >=8.3 | MIT | dev: тесты |
| ruff | >=0.6 | MIT | dev: линтер и форматтер |
| numpy | >=2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | векторы эмбеддингов, косинусная близость |
| pdfplumber | >=0.11.11 | MIT | таблицы из PDF (в т.ч. таблицы неисправностей) |
| pillow | >=13.0.0 | MIT-CMU | рендер страницы PDF в JPEG для OCR |
| pymorphy3 | >=2.0.6 | MIT | приведение слов к начальной форме для BM25 (словари pymorphy3-dicts-ru, MIT) |
| pypdfium2 | >=5.15.2 | BSD-3-Clause, Apache-2.0 | текст страниц PDF, рендер страниц (PyMuPDF не берём: AGPL) |
| openpyxl | >=3.1.5 | MIT | dev: заполнение шаблона организаторов (`make cost-xlsx`) |
| hatchling | >=1.25 | MIT | сборка пакета |

## Прочие компоненты

| Компонент | Лицензия / условия | Зачем |
|---|---|---|
| uv | MIT / Apache-2.0 | менеджер зависимостей |
| Заглушки Mock ML и Mock ТОиР, `data/vehicles.json`, `data/fault_types.json` (`vendor/neurodvs_mock/`, `data/`) | материалы ООО «НейроДВС» для команд хакатона, синтетические | контракт API и тестовые данные по ТЗ |
| Руководства по эксплуатации и ремонту ЯМЗ, ЗМЗ (6 PDF) | материалы заказчика; в репозиторий не входят | база знаний агента |
| gitleaks | MIT | поиск секретов в pre-commit и CI |
| Docker-образ `python:3.12-slim` | PSF и лицензии пакетов Debian | образ для запуска |
| GitHub Actions `actions/checkout`, `actions/setup-python` | MIT | CI |
| Корневой сертификат Минцифры (Russian Trusted Root CA), `src/service/certs/` | публичный, [gosuslugi.ru/crt](https://www.gosuslugi.ru/crt) | доверие TLS к GigaChat и другим сервисам на российских сертификатах |
| GitHub CLI `gh` (предустановлен на раннерах GitHub) | MIT | комментарий превью в PR |
| Yandex Cloud CLI `yc` | условия использования Yandex Cloud | превью-деплой PR |
| Yandex Cloud Serverless Containers, Container Registry | условия использования Yandex Cloud | хостинг превью PR |
| Yandex Vision OCR, Yandex AI Studio эмбеддинги (`text-search-doc`, `text-search-query`) | условия использования Yandex Cloud | OCR страниц без текстового слоя, поиск по смыслу в руководствах |

## Ранее созданные наработки

Каркас репозитория (CI, хуки, Makefile, сверки) подготовлен до хакатона в открытом репозитории команды.
