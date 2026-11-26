#!/bin/sh
# Локальные тестовые серверы с файлом PID (решение Валерия: без прямого kill — гасим только свой процесс).
#
#   sh scripts/local_server.sh start PORT [APP]   — uvicorn в фоне; PID → .state/run-local-PORT.pid, лог рядом
#   sh scripts/local_server.sh stop PORT          — гасит ТОЛЬКО процесс из файла: жив, это uvicorn и именно этот порт
#
# APP — service.main:app (по умолчанию) или mock_ml.app:app / mock_toir.app:app (заглушки из vendor/neurodvs_mock).
set -eu

cmd=${1:-}
port=${2:-}
app=${3:-service.main:app}
case "$port" in '' | *[!0-9]*) echo "нужен порт: $0 start|stop PORT [APP]" >&2; exit 2 ;; esac

dir=.state
pidf="$dir/run-local-$port.pid"
logf="$dir/run-local-$port.log"
mkdir -p "$dir"

ours() { # PID жив, это uvicorn и слушает именно этот порт
  pid=$1
  kill -0 "$pid" 2>/dev/null || return 1
  line=$(ps -o command= -p "$pid" 2>/dev/null || true)
  case "$line" in *uvicorn*"--port $port"*) return 0 ;; *) return 1 ;; esac
}

case "$cmd" in
start)
  if [ -f "$pidf" ] && ours "$(cat "$pidf")"; then
    echo "уже запущен: порт $port, PID $(cat "$pidf")"
    exit 0
  fi
  case "$app" in
  mock_*) set -- uv run uvicorn --app-dir vendor/neurodvs_mock "$app" --port "$port" ;;
  *)
    if [ -f .env ]; then set -- uv run --env-file .env uvicorn "$app" --port "$port"
    else set -- uv run uvicorn "$app" --port "$port"; fi ;;
  esac
  nohup "$@" >"$logf" 2>&1 &
  echo $! >"$pidf"
  i=0
  until curl -sS -o /dev/null "http://127.0.0.1:$port/" 2>/dev/null; do  # ответил хоть чем-то — сервер поднят
    i=$((i + 1))
    if [ "$i" -ge 40 ]; then echo "порт $port не ответил за 20 с — лог: $logf" >&2; exit 1; fi
    sleep 0.5
  done
  echo "запущен: $app на порту $port, PID $(cat "$pidf"), лог $logf"
  ;;
stop)
  if [ ! -f "$pidf" ]; then echo "нет файла $pidf — нечего останавливать"; exit 0; fi
  pid=$(cat "$pidf")
  if ! ours "$pid"; then
    echo "PID $pid не наш uvicorn на порту $port (уже остановлен?) — файл удалён, процессы не трогаю"
    rm -f "$pidf"
    exit 0
  fi
  kill "$pid"
  i=0
  while kill -0 "$pid" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 20 ]; then echo "PID $pid не остановился за 10 с" >&2; exit 1; fi
    sleep 0.5
  done
  rm -f "$pidf"
  echo "остановлен: порт $port, PID $pid"
  ;;
*) echo "команда: start | stop" >&2; exit 2 ;;
esac
