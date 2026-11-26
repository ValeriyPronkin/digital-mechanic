# Сторонние компоненты

Положение, п. 4.4, 4.8, 9.1. Раздел «Python-зависимости» CI сверяет с `pyproject.toml`
(`scripts/check_third_party.py`): прямые зависимости, лицензия — из метаданных пакета.
Транзитивные зависимости и точные версии — в `uv.lock`.

## Python-зависимости

| Пакет | Версия | Лицензия | Зачем |
|---|---|---|---|
| fastapi | >=0.115 | MIT | HTTP API и страница |
| uvicorn | >=0.30 | BSD-3-Clause | ASGI-сервер |
| httpx | >=0.27 | BSD-3-Clause | dev: тестовый клиент FastAPI |
| mypy | >=1.11 | MIT | dev: проверка типов |
| pytest | >=8.3 | MIT | dev: тесты |
| ruff | >=0.6 | MIT | dev: линтер и форматтер |
| hatchling | >=1.25 | MIT | сборка пакета |

## Прочие компоненты

| Компонент | Лицензия / условия | Зачем |
|---|---|---|
| uv | MIT / Apache-2.0 | менеджер зависимостей |
| gitleaks | MIT | поиск секретов в pre-commit и CI |
| Docker-образ `python:3.12-slim` | PSF и лицензии пакетов Debian | образ для запуска |
| GitHub Actions `actions/checkout`, `actions/setup-python` | MIT | CI |
| Корневой сертификат Минцифры (Russian Trusted Root CA), `src/service/certs/` | публичный, [gosuslugi.ru/crt](https://www.gosuslugi.ru/crt) | доверие TLS к GigaChat и другим сервисам на российских сертификатах |
| GitHub CLI `gh` (предустановлен на раннерах GitHub) | MIT | комментарий превью в PR |
| Yandex Cloud CLI `yc` | условия использования Yandex Cloud | превью-деплой PR |
| Yandex Cloud Serverless Containers, Container Registry | условия использования Yandex Cloud | хостинг превью PR |

## Ранее созданные наработки

Каркас репозитория (CI, хуки, Makefile, сверки) подготовлен до хакатона в открытом репозитории команды.
