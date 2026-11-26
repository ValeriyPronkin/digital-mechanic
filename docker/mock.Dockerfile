# Образ заглушек заказчика (vendor/neurodvs_mock) как есть: Mock ML или Mock ТОиР — выбирает command в compose.yaml.
FROM python:3.12-slim
WORKDIR /mock
COPY vendor/neurodvs_mock/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 1000 app
COPY vendor/neurodvs_mock/ ./
USER app
