# Интерфейс v2 (issue #52, web/ — автор Никита Пронкин): сборка Vite → статические файлы, раздаются по /v2.
FROM node:24-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.12.24 \
    && useradd --create-home --uid 1000 app

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data
# Парк и справочник — материалы задачи, не в git: до сборки — make fetch-materials (TASK_MATERIALS_URL)
RUN test -f data/vehicles.json && test -f data/fault_types.json \
    || { echo "нет data/vehicles.json или data/fault_types.json — сначала make fetch-materials" >&2; exit 1; }
COPY --from=web /web/dist ./web/dist
RUN uv sync --frozen --no-dev && chown -R app:app /app

USER app
# Версия в /health (поле build): коммит и время сборки — от workflow (`--build-arg`), без .git в образе.
# Аргументы — после установки зависимостей: новый коммит не сбрасывает кэш слоёв.
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    GIT_SHA=$GIT_SHA \
    BUILD_TIME=$BUILD_TIME
# Порт — из PORT (Serverless Containers передаёт его сам, обычно 8080); локально, в compose и смоуке — 8000.
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn service.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
