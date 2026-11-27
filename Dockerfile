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
COPY scripts/materials.py ./scripts/materials.py
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
# Материалы задачи (карточки ТС, ответы ML, справочник) в git не входят. Есть в образе (собран после
# `make materials`) — берутся оттуда; нет — при старте скачиваются по MATERIALS_URL в /tmp/materials
# и сверяются с data/materials.lock.json; DATA_DIR указывает на папку с ними.
ENTRYPOINT ["python", "scripts/materials.py", "run", "--only", "data/", "--fallback", "/tmp/materials", \
            "--env", "DATA_DIR={dir}", "--"]
# Порт — из PORT (Serverless Containers передаёт его сам, обычно 8080); локально, в compose и смоуке — 8000.
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn service.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
