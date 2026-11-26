#!/bin/sh
# Смоук из чистого окружения: собрать образ, поднять, дождаться /health, остановить.
set -eu
PORT="${PORT:-8000}"
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
