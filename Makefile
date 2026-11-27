.PHONY: video e2e fetch-materials run-local stop-local mocks-local stop-mocks-local parts-demo stop-parts-demo web web-test engineer-pack demo-check reset-demo logs spend-probe eval-open eval-parts eval-golden eval-sweep eval-stability setup install run mocks check lint types test stubs third-party secrets hooks smoke fmt cost cost-xlsx cost-final index kb-publish kb-fetch pages-render pages-publish

PORT ?= 8000

install:
	uv sync --frozen

## Материалы задачи (заглушки, парк, справочник) — не в git: скачать по TASK_MATERIALS_URL (.env) или MATERIALS=путь
fetch-materials: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/fetch_materials.py $(MATERIALS)

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

## Себестоимость по участкам на настоящей модели (issue #16): reports/cost.md + reports/cost/<LABEL>.csv
LABEL ?= $(shell date +%Y%m%d-%H%M)
## Пакет для инженера (#40 п. 7): все отклонения и сбои на стенде → reports/engineer-pack-<дата>.html (не в git: ответы заглушек; ≈15 мин, ≈11 ₽)
STAND_URL ?= https://bbab8qkqhuhg3ere9dam.containers.yandexcloud.net/
engineer-pack: install
	uv run python scripts/engineer_pack.py $(STAND_URL) $(PACK_ARGS)

## Сцены видео в браузере (Playwright): телефон WebKit 390×664 и ноутбук Chromium → reports/e2e/<метка>/report.md
## По умолчанию — make run-local (:8010); стенд или превью — E2E_URL=…; E2E_ARGS="--only phone --send-ticket --break-images"
E2E_URL ?= http://127.0.0.1:$(PORT_LOCAL)
e2e: install
	uv run python -m playwright install webkit chromium
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/e2e.py $(E2E_URL) $(E2E_ARGS)

## Маршрут дубля на стенде /v2 (B418HK98/S-0009, H142OX78/S-0113, запасная M739BA198/S-0104): таблица шагов
## и секунд; код 0 = «готово к дублю», 3 = только «ждёт PR #N», 1 = ❌. Заявку не шлёт. ARGS=--help — параметры
## Видео для жюри одним дублем (Playwright Chromium, настоящая модель): ускоряется только ожидание ответа модели (ffmpeg)
## → reports/video/<метка>-<тема>/video.mp4 и scenes.md с таймкодами. Перед дублем — make reset-demo.
## E2E_URL — стенд; VIDEO_ARGS="--theme light --pace 1.6"
video: install
	uv run python -m playwright install chromium
	uv run --with imageio-ffmpeg $(if $(wildcard .env),--env-file .env,) python scripts/video.py $(E2E_URL) $(VIDEO_ARGS)

demo-check: install
	uv run python scripts/demo_check.py $(or $(STAND),$(STAND_URL)) $(ARGS)

## Сброс демо-машин перед повторным дублем: нити v2 и отметки заявок в бакете (статический ключ из .env), заявки
## в локальной SQLite; стенд только читает. Сначала ARGS=--dry-run. Перезапуск стенда — команда в конце вывода
reset-demo: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/reset_demo.py --stand $(or $(STAND),$(STAND_URL)) $(ARGS)

cost: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/cost_report.py --label $(LABEL)

## Выложить индекс новой версией в бакет S3_BUCKET (статический ключ из .env; index/LATEST — последним). PDF — KB_ARGS=--manuals
kb-publish: install
	uv run $(if $(wildcard .env),--env-file .env,) python -m service.kb_store publish $(KB_ARGS)

## Проверить выкладку: скачать index/LATEST из бакета в каталог KB_OUT (по умолчанию .state/kb-check)
kb-fetch: install
	uv run $(if $(wildcard .env),--env-file .env,) python -m service.kb_store fetch --out $(or $(KB_OUT),.state/kb-check)

## Картинки страниц для «стр. N»: отрисовать в .state/pages (по одному PDF) — pages-render; загрузить в pages/ — pages-publish
pages-render: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/pages_publish.py $(if $(DOC),--doc $(DOC),)

pages-publish: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/pages_publish.py --upload $(if $(DOC),--doc $(DOC),)

## Шаблон организаторов по замеру → сдаваемый reports/cost-calculator.xlsx (жёлтые ячейки; шаблон — он же или COST_TEMPLATE).
## Другой замер для сравнения — в другой файл: make cost-xlsx XLSX_LABEL=gigachat-1 XLSX_OUT=.state/gigachat.xlsx
cost-xlsx: install
	uv run python scripts/cost_xlsx.py $(if $(XLSX_LABEL),--label $(XLSX_LABEL),) $(if $(XLSX_OUT),--out $(XLSX_OUT),)

## Себестоимость на текущем коммите одной командой (перед сдачей, после последних слияний): живой замер всех
## сценариев, 2 прогона (≈1 ₽; нужны .env с ключом модели и Yandex и индекс .index/) → reports/cost/final.*,
## reports/cost.md и сдаваемый шаблон reports/cost-calculator.xlsx. Провал проверки качества — код ≠ 0, шаблон не пишется.
cost-final: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/cost_report.py --label final --repeat 2
	uv run python scripts/cost_xlsx.py --label final

## Открытая половина вопросов приёмщика на настоящей модели (issue #28): reports/eval-open.md (вопросы — вне git)
eval-open: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/eval_open.py --label $(or $(LABEL),$(shell date +%Y%m%d-%H%M))

## Многоязычный набор (27.11): вопросы открытой половины на узб./тадж./каз. и ломаном русском — reports/eval-multi.md
## Вопросы — вне git: .state/questions_multi.jsonl (или EVAL_MULTI=путь); засчитано — страница, числа, язык ответа
eval-multi: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/eval_open.py --set multi --label $(or $(LABEL),$(shell date +%Y%m%d-%H%M))

## Контрольные вопросы Никиты (36 сверенных + 48 написанных вслепую) через /api/v2/chat работающего сервиса:
## reports/eval-golden.md. Сервис — make run (EVAL_URL по умолчанию http://127.0.0.1:8000) или стенд; заявку не шлёт
eval-golden: install
	uv run python scripts/eval_golden.py --set $(or $(EVAL_SET),all) --label $(or $(LABEL),$(shell date +%Y%m%d-%H%M)) $(if $(EVAL_URL),--url $(EVAL_URL),) $(EVAL_ARGS)

## Живой агент по каждой ячейке двигатель × неисправность и особым проверкам (67 нитей): диагноз → «Создать заявку»
## до листа подтверждения, без отправки — reports/eval-sweep.md. Сервис — make run (EVAL_URL) или стенд
eval-sweep: install
	uv run python scripts/eval_sweep.py --label $(or $(LABEL),$(shell date +%Y%m%d-%H%M)) $(if $(EVAL_URL),--url $(EVAL_URL),) $(EVAL_ARGS)

## Набор «какой инструмент / какие запчасти» (ночь 27→28.11): .state/questions_parts.jsonl — reports/eval-parts.md
eval-parts: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/eval_open.py --set parts --label $(or $(LABEL),$(shell date +%Y%m%d-%H%M))

## Стабильность (штурман 26.11): RUNS прогонов eval-open с префиксом PREFIX и сводка по ним
eval-stability: install
	for i in $(shell seq 1 $(or $(RUNS),3)); do uv run $(if $(wildcard .env),--env-file .env,) python scripts/eval_open.py --label $(PREFIX)-$$i || exit 1; done
	uv run python scripts/eval_stability.py $(PREFIX)

## Проверка условной записи на настоящем бакете (issue #11): объект spend/probe-*, после — удаляется. Запускает человек
spend-probe: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/spend_probe.py

## Журнал стенда за период (issue #27): logs/<дата>/*.jsonl из бакета → сводка (.state/stand-logs-*.md). Только чтение
logs: install
	uv run $(if $(wildcard .env),--env-file .env,) python scripts/stand_logs.py $(if $(SINCE),--since $(SINCE),) $(if $(UNTIL),--until $(UNTIL),)

## Интерфейс v2 (issue #52): сборка web/ → web/dist (раздаётся по /v2); тесты фронта
web:
	cd web && npm ci --no-audit --no-fund && npm run build

web-test:
	cd web && npm ci --no-audit --no-fund && npm test

## Локальные тестовые серверы с файлом PID (.state/run-local-PORT.pid): гасится только свой процесс, без kill вручную
PORT_LOCAL ?= 8010
run-local:
	sh scripts/local_server.sh start $(or $(PORT),$(PORT_LOCAL))

stop-local:
	sh scripts/local_server.sh stop $(or $(PORT),$(PORT_LOCAL))

## Заглушки заказчика в фоне: Mock ML :8001, Mock ТОиР :8002 (остановить — make stop-mocks-local)
mocks-local:
	sh scripts/local_server.sh start 8001 mock_ml.app:app
	sh scripts/local_server.sh start 8002 mock_toir.app:app

stop-mocks-local:
	sh scripts/local_server.sh stop 8001
	sh scripts/local_server.sh stop 8002

## Демо двух ВЫМЫШЛЕННЫХ поставщиков запчастей: HTTP-заглушка :8003; сервис — PARTS_SUPPLIERS=data/demo/suppliers
parts-demo:
	sh scripts/local_server.sh start 8003 service.parts_demo_api:app
	@echo "сервис с двумя поставщиками: PARTS_SUPPLIERS=data/demo/suppliers make run-local"

stop-parts-demo:
	sh scripts/local_server.sh stop 8003

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
