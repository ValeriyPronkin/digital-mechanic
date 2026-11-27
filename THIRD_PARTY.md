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
| pyyaml | >=6.0 | MIT | реестры поиска из прототипа Никиты (`registry/glossary.yaml`, `registry/page_scope.yaml`) |
| openpyxl | >=3.1.5 | MIT | dev: заполнение шаблона организаторов (`make cost-xlsx`) |
| hatchling | >=1.25 | MIT | сборка пакета |

## JavaScript-зависимости (web/)

Интерфейс v2 (`web/`, `/v2`, issue #52) — код второго прототипа команды, автор **Никита Пронкин**
(`pronkinnikita/digital-mechanic`, каталог `web/`, коммит `11f0f72`), создан в ходе спринта. Раздел CI сверяет
с `web/package.json` (`scripts/check_third_party.py`); лицензия — из метаданных пакета, точные версии — в
`web/package-lock.json`.

| Пакет | Версия | Лицензия | Зачем |
|---|---|---|---|
| react | 19.3.1 | MIT | интерфейс v2 |
| react-dom | 19.3.1 | MIT | интерфейс v2 |
| tailwindcss | 4.3.5 | MIT | стили интерфейса v2 |
| @tailwindcss/vite | 4.3.5 | MIT | подключение tailwind к сборке |
| vite | 8.3.6 | MIT | dev: сборка интерфейса v2 |
| @vitejs/plugin-react | 6.1.2 | MIT | dev: сборка React |
| typescript | 7.0.2 | Apache-2.0 | dev: проверка типов интерфейса |
| @types/node | 24.19.2 | MIT | dev: типы |
| @types/react | 19.3.0 | MIT | dev: типы |
| @types/react-dom | 19.3.0 | MIT | dev: типы |
| oxlint | 1.95.0 | MIT | dev: линтер интерфейса |
| prettier | 3.10.1 | MIT | dev: форматтер интерфейса |

## Модели и внешние API в продукте

Всё, во что сервис ходит по сети. Ключи — только в `.env` и в секретах стенда.

| Компонент | Условия | Зачем | Где в коде |
|---|---|---|---|
| DeepSeek API (`api.deepseek.com`), модель `deepseek-chat` по умолчанию, другая — `LLM_MODEL` | условия DeepSeek, оплата за токены | модель агента: выбор инструментов, объяснение, ответ по руководству, план поиска, перевод ответа на язык вопроса. На стенде `LLM_PROVIDER=deepseek` (`/health` → `llm_provider`) | `src/service/llm.py` |
| GigaChat API (Сбер), модель `GigaChat-2-Max` | условия Сбера, оплата за токены | второй провайдер модели, `LLM_PROVIDER=gigachat`. На стенде не включён; сравнение цены и качества — `reports/cost.md` | `src/service/llm.py` |
| Yandex AI Studio, эмбеддинги `text-search-doc` и `text-search-query` | условия Yandex Cloud | поиск по смыслу в руководствах: векторы фрагментов при сборке индекса и вектор вопроса при каждом поиске | `src/service/manuals/yandex.py` |
| Yandex Vision OCR, модель `page` | условия Yandex Cloud | текст страниц PDF без текстового слоя, только при сборке индекса (`make index`) | `src/service/manuals/yandex.py` |
| Yandex SpeechKit, распознавание API v1 | условия Yandex Cloud | вопрос голосом: русский, узбекский, казахский, английский | `src/service/voice.py` |
| Yandex SpeechKit, синтез API v1 и v3 | условия Yandex Cloud | короткий ответ вслух. Голоса: `zahar` (русский, D-15), `nigora` (узбекский), `amira` (казахский), `john` (английский) | `src/service/voice.py`, `src/service/language.py` |
| Yandex Object Storage, частный бакет | условия Yandex Cloud | индекс руководств и PDF, картинки страниц, общий счётчик расходов, журнал стенда, кэш озвучки, нити разговоров | `src/service/kb_store.py`, `spend.py`, `stand_log.py`, `pages.py`, `voice.py`, `api_v2.py` |
| Yandex Cloud Serverless Containers, Container Registry, IAM (токен из метаданных) | условия Yandex Cloud | стенд и превью PR; стенд читает бакет по токену своего сервисного аккаунта | `.github/workflows/stand.yml`, `preview.yml`, `src/service/kb_store.py` |
| Mock ML и Mock ТОиР | материалы ООО «НейроДВС» | сервис акустической проверки и ТОиР по контракту ТЗ v6; адреса — `MOCK_ML_URL`, `MOCK_TOIR_URL` | `vendor/neurodvs_mock/` |

Поставщики запчастей в `data/demo/suppliers/` вымышленные, их HTTP-заглушка запускается локально (`make parts-demo`).
На стенде поставщиков нет (`STUB: parts-catalog` в README).

## Прочие компоненты

| Компонент | Лицензия / условия | Зачем |
|---|---|---|
| uv | MIT / Apache-2.0 | менеджер зависимостей |
| Заглушки Mock ML и Mock ТОиР, `data/vehicles.json`, `data/fault_types.json` (`vendor/neurodvs_mock/`, `data/`) | материалы ООО «НейроДВС» для команд хакатона, синтетические | контракт API и тестовые данные по ТЗ |
| Руководства по эксплуатации и ремонту ЯМЗ, ЗМЗ (6 PDF) | материалы заказчика; в репозиторий не входят | база знаний агента |
| gitleaks | MIT | поиск секретов в pre-commit и CI |
| Docker-образ `python:3.12-slim` | PSF и лицензии пакетов Debian | образ для запуска |
| Docker-образ `node:24-bookworm-slim` | MIT и лицензии пакетов Debian | стадия сборки интерфейса v2 |
| GitHub Actions `actions/checkout`, `actions/setup-python`, `actions/setup-node` | MIT | CI |
| Корневой сертификат Минцифры (Russian Trusted Root CA), `src/service/certs/` | публичный, [gosuslugi.ru/crt](https://www.gosuslugi.ru/crt) | доверие TLS к GigaChat и другим сервисам на российских сертификатах |
| GitHub CLI `gh` (предустановлен на раннерах GitHub) | MIT | комментарий превью в PR |
| Yandex Cloud CLI `yc` | условия использования Yandex Cloud | деплой стенда и превью PR |

## Ранее созданные наработки

**Шаблон репозитория `ai-forge`.** Сделан Валерием Пронкиным до хакатона, с 16 по 25 ноября 2026 года, в
репозитории `ValeriyPronkin/ai-forge`, каталог `template/`. Это единственная наработка, сделанная до спринта.

Проверить это можно по истории этого репозитория:

- первый коммит, `27c9ef5` (26.11.2026, 11:19 по Москве), — шаблон `ai-forge`, перенесённый файл в файл скриптом
  `kit/new-project.sh`;
- код продукта начинается с коммита `fce39d3` (26.11.2026, 12:17 по Москве). Всё, что дал шаблон, видно в
  `27c9ef5`: `git show --stat 27c9ef5`;
- репозиторий шаблона закрытый; доступ на чтение дадим по запросу организаторов.

В шаблоне было:

- сервис на FastAPI в 30 строк: `/health` и страница-заглушка `/` (`src/service/main.py`, `static/index.html`);
- `src/service/tls.py` и корневой сертификат Минцифры для TLS к российским API;
- `Makefile` (`setup`, `run`, `check` = линт, типы, тесты, сверки, секреты; `smoke`), `Dockerfile`, `compose.yaml`,
  `pyproject.toml`, `uv.lock`, `.env.example`;
- CI (`.github/workflows/ci.yml`), превью PR и постоянный стенд в Yandex Cloud Serverless Containers
  (`preview.yml`, `stand.yml`);
- git-хуки (gitleaks; запрет push в `main`), `scripts/check_stubs.py`, `scripts/check_third_party.py`,
  `scripts/smoke.sh`, четыре файла тестов этих частей, `.claude/settings.json`;
- правила работы агента (`CLAUDE.md`) и пустые шаблоны `STATUS.md` и `DECISIONS.md`.

Кода продукта в шаблоне нет. Агент, инструменты, индекс и поиск по руководствам, матрица «код × двигатель»,
проверка цифр, заявка, голос, страница парка и интерфейс написаны в срок хакатона, начиная с `fce39d3`.

**Не наработка, а код второго участника команды из этого же спринта.** Интерфейс v2 (`web/`) и второй поиск по
документам (`src/service/nikita/`, `registry/glossary.yaml`, `registry/page_scope.yaml`) перенесены из прототипа
Никиты Пронкина `pronkinnikita/digital-mechanic`, начатого 26.11.2026 в 11:55 по Москве; `web/` взят с коммита
`11f0f72` (issue #52). Прототип раскрывает свою наработку: порядок работы с задачами и идея автоматической проверки текстов по
документу о тоне — из прошлого проекта Никиты Пронкина `hotel-truth` (закрытый репозиторий, доступ на чтение —
по запросу организаторов). Кода оттуда нет: проверка текстов написана в срок хакатона в версии Никиты и
перенесена сюда.

**Инструмент разработки.** Код написан с помощью Claude Code (Anthropic): у 162 из 231 коммита `main` на
27.11.2026 есть строка `Co-Authored-By: Claude Opus 5.5`. В самом продукте модели Anthropic не вызываются.
