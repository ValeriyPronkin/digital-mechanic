# Общие шаги деплоя стенда в Yandex Cloud Serverless Containers (подключается из .github/workflows/stand.yml).
# Требует: yc в PATH с настроенным профилем, jq, curl; переменные YC_SA_ID, STAND_MIN_INSTANCES;
# STAND_CONCURRENCY — запросов на один экземпляр (по умолчанию 4): интерфейс v2 шлёт запросы параллельно
# (чат, страница, парк, озвучка), при 1 каждый параллельный запрос будит ещё один экземпляр с холодным стартом.

# Тёплые экземпляры (STAND_MIN_INSTANCES) — квота облака serverless.containersWorkersProvisioned = 2 на все контейнеры:
# тёплыми бывают только основной и заглушка ML, ТОиР всегда 0 (вызов: `X=$(STAND_MIN_INSTANCES=0 deploy_container …)`).

# ycr АРГУМЕНТЫ… — yc с повтором при сетевом сбое раннера («failed to initialize SDK», «list api endpoints»,
# обрыв соединения): до 3 попыток с паузой. Другие ошибки (квота, нет прав) не повторяются — сразу код возврата.
# stdout yc проходит как есть (для `$(ycr … --format json)`), stderr последней попытки — в stderr.
ycr() {
  err=$(mktemp)
  n=1
  while :; do
    if yc "$@" 2>"$err"; then
      rm -f "$err"
      return 0
    fi
    if [ "$n" -ge "${YC_TRIES:-3}" ] || ! grep -qiE 'failed to initialize SDK|list api endpoints|context deadline exceeded|connection reset|i/o timeout|code = Unavailable' "$err"; then
      cat "$err" >&2
      rm -f "$err"
      return 1
    fi
    echo "yc: сетевой сбой (попытка $n из ${YC_TRIES:-3}), повтор через ${YC_RETRY_PAUSE:-10} с: $(head -c 200 "$err")" >&2
    n=$((n + 1))
    sleep "${YC_RETRY_PAUSE:-10}"
  done
}

# deploy_container ИМЯ ОБРАЗ ПАМЯТЬ ТАЙМАУТ [доп. аргументы yc ...] → печатает URL контейнера (со слешем в конце).
# Любая ошибка yc — код возврата 1 (вызов `X=$(deploy_container …)` под set -e валит шаг): внутри $(...) set -e
# не действует, и раньше упавший `revision deploy` (квота) молча оставлял старую ревизию при зелёном шаге.
deploy_container() {
  name=$1 image=$2 memory=$3 timeout=$4
  shift 4
  if ! ycr serverless container get --name "$name" >/dev/null 2>&1; then
    ycr serverless container create --name "$name" >/dev/null || { echo "Не создали контейнер $name" >&2; return 1; }
  fi
  ycr serverless container revision deploy \
    --container-name "$name" \
    --image "$image" \
    --service-account-id "$YC_SA_ID" \
    --memory "$memory" \
    --cores 1 \
    --execution-timeout "$timeout" \
    --min-instances "$STAND_MIN_INSTANCES" \
    --concurrency "${STAND_CONCURRENCY:-4}" \
    "$@" >/dev/null || { echo "Ревизия $name не задеплоена (тёплых: $STAND_MIN_INSTANCES) — см. ошибку yc выше" >&2; return 1; }
  ycr serverless container allow-unauthenticated-invoke --name "$name" >/dev/null || return 1
  url=$(ycr serverless container get --name "$name" --format json | jq -r '.url')
  if [ -z "$url" ] || [ "$url" = "null" ]; then
    echo "Не получили url контейнера $name" >&2
    return 1
  fi
  printf '%s/\n' "${url%/}"
}

# wait_health URL — ждёт 200 и "status" в URL/health. Терпеливо (стенд 27.11: с раннера GitHub заглушка отвечала
# дольше 30 с, с Mac — за ~17 с): запрос до STAND_HEALTH_REQUEST с (60), пауза STAND_HEALTH_PAUSE с (10),
# всего до STAND_HEALTH_BUDGET с (300). Код 1 — не дождались; что делать с этим, решает вызывающий шаг.
wait_health() {
  start=$(date +%s)
  i=0
  while :; do
    i=$((i + 1))
    if body=$(curl -fsS --max-time "${STAND_HEALTH_REQUEST:-60}" "${1}health" 2>/dev/null); then
      case "$body" in
        *'"status"'*) echo "${1}health: ок (попытка $i, $(($(date +%s) - start)) с)"; return 0 ;;
        *) echo "${1}health: нет status" >&2; return 1 ;;
      esac
    fi
    if [ $(($(date +%s) - start + ${STAND_HEALTH_PAUSE:-10})) -ge "${STAND_HEALTH_BUDGET:-300}" ]; then
      echo "${1}health не ответил 200 за $(($(date +%s) - start)) с ($i попыток)" >&2
      return 1
    fi
    sleep "${STAND_HEALTH_PAUSE:-10}"
  done
}
