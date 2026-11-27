# Образ заглушек заказчика (vendor/neurodvs_mock) как есть. Какое приложение — MOCK_APP:
# mock_ml.app:app (Mock ML) или mock_toir.app:app (Mock ТОиР). Порт — из PORT (Serverless Containers задаёт сам).
FROM python:3.12-slim
WORKDIR /mock
COPY vendor/neurodvs_mock/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 1000 app
COPY vendor/neurodvs_mock/ ./
# Данные заглушек — материалы задачи вне git: есть в образе — из образа, нет — при старте по MATERIALS_URL
# в /tmp/materials (сверка с замком), путь к ним — в MOCK_DATA_PATH. Код заглушек не меняем.
COPY scripts/materials.py ./scripts/materials.py
COPY data/materials.lock.json ./data/materials.lock.json
USER app
ENV MOCK_APP=mock_ml.app:app PYTHONUNBUFFERED=1
EXPOSE 8001
ENTRYPOINT ["python", "scripts/materials.py", "run", "--only", "vendor/neurodvs_mock/data/", \
            "--strip", "vendor/neurodvs_mock/", "--fallback", "/tmp/materials", \
            "--env", "MOCK_DATA_PATH={dir}/vehicles.json", "--"]
CMD ["sh", "-c", "exec uvicorn \"$MOCK_APP\" --host 0.0.0.0 --port ${PORT:-8001}"]
