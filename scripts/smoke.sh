#!/bin/sh
# Смоук из чистого окружения: собрать образ, поднять, дождаться /health, остановить.
set -eu
PORT="${PORT:-8000}"
# Материалы задачи (парк, ответы ML) — вне git. Без них и без ссылки MATERIALS_URL заглушки не стартуют:
# смоук пропускается с предупреждением, а не краснеет. В CI ссылку даёт секрет MATERIALS_URL.
if ! python3 scripts/materials.py --check >/dev/null 2>&1 \
  && [ -z "${MATERIALS_URL:-}" ] && ! grep -qs '^MATERIALS_URL=.' .env; then
  echo "::warning::smoke: пропущен — нет материалов задачи и не задан MATERIALS_URL (README, «Запуск»)"
  exit 0
fi
cleanup() { docker compose down --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker compose up -d --build
i=0
until HEALTH=$(curl -fsS "http://localhost:${PORT}/health"); do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "smoke: /health не ответил за 60 с" >&2
    docker compose logs >&2
    exit 1
  fi
  sleep 2
done
echo "$HEALTH"
case "$HEALTH" in
  *'"status":"ok"'*) echo "smoke: ок" ;;
  *) echo "smoke: /health без status ok" >&2; exit 1 ;;
esac
