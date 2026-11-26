FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.12.24 \
    && useradd --create-home --uid 1000 app

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data
RUN uv sync --frozen --no-dev && chown -R app:app /app

USER app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
# Порт — из PORT (Serverless Containers передаёт его сам, обычно 8080); локально, в compose и смоуке — 8000.
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn service.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
