.PHONY: setup install run mocks check lint types test stubs third-party secrets hooks smoke fmt index kb-publish kb-fetch

PORT ?= 8000

install:
	uv sync --frozen

## Первый запуск после клона: зависимости и git-хуки (pre-commit — gitleaks, pre-push — запрет push в main)
setup: install hooks

hooks:
	git config core.hooksPath .githooks
	@echo "git-хуки включены: .githooks (pre-commit, pre-push)"

## Одна команда для запуска: зависимости и сервис на http://localhost:$(PORT)
run: install
	uv run $(if $(wildcard .env),--env-file .env,) uvicorn service.main:app --host 0.0.0.0 --port $(PORT)

## Заглушки заказчика без Docker: Mock ML на :8001, Mock ТОиР на :8002 (Ctrl+C — остановить обе)
mocks: install
	uv run uvicorn --app-dir vendor/neurodvs_mock mock_ml.app:app --port 8001 & \
	uv run uvicorn --app-dir vendor/neurodvs_mock mock_toir.app:app --port 8002; \
	kill $$! 2>/dev/null; wait

## Индекс руководств одной командой: PDF из MANUALS_DIR → INDEX_DIR (по умолчанию .index/). Повторно — из кэша
index: install
	uv run $(if $(wildcard .env),--env-file .env,) python -m service.manuals build

## Выложить индекс новой версией в бакет S3_BUCKET (статический ключ из .env; index/LATEST — последним). PDF — KB_ARGS=--manuals
kb-publish: install
	uv run $(if $(wildcard .env),--env-file .env,) python -m service.kb_store publish $(KB_ARGS)

## Проверить выкладку: скачать index/LATEST из бакета в каталог KB_OUT (по умолчанию .state/kb-check)
kb-fetch: install
	uv run $(if $(wildcard .env),--env-file .env,) python -m service.kb_store fetch --out $(or $(KB_OUT),.state/kb-check)

## Всё, что проверяет CI, кроме смоука в Docker. Зелёный = код возврата 0.
check: lint types test stubs third-party secrets

lint:
	uv run ruff check .
	uv run ruff format --check .

## Привести формат в порядок (lint падает на неотформатированном коде)
fmt:
	uv run ruff check --fix .
	uv run ruff format .

types:
	uv run mypy

test:
	uv run pytest -q

## Каждая метка STUB: <id> в коде описана в README «Ограничения»
stubs:
	uv run python scripts/check_stubs.py

## Каждая зависимость из pyproject — строка в THIRD_PARTY.md с лицензией (Положение п. 4.4, 4.8, 9.1)
third-party:
	uv run python scripts/check_third_party.py

secrets:
	gitleaks git --no-banner --redact

## Смоук из чистого окружения: сборка образа, docker compose up, ожидание /health
smoke:
	sh scripts/smoke.sh
