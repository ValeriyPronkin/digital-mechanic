# Общие шаги деплоя стенда в Yandex Cloud Serverless Containers (подключается из .github/workflows/stand.yml).
# Требует: yc в PATH с настроенным профилем, jq, curl; переменные YC_SA_ID, STAND_MIN_INSTANCES;
# STAND_CONCURRENCY — запросов на один экземпляр (по умолчанию 4): интерфейс v2 шлёт запросы параллельно
# (чат, страница, парк, озвучка), при 1 каждый параллельный запрос будит ещё один экземпляр с холодным стартом.

# deploy_container ИМЯ ОБРАЗ ПАМЯТЬ ТАЙМАУТ [доп. аргументы yc ...] → печатает URL контейнера (со слешем в конце)
deploy_container() {
  name=$1 image=$2 memory=$3 timeout=$4
  shift 4
  if ! yc serverless container get --name "$name" >/dev/null 2>&1; then
    yc serverless container create --name "$name" >/dev/null
  fi
  yc serverless container revision deploy \
    --container-name "$name" \
    --image "$image" \
    --service-account-id "$YC_SA_ID" \
    --memory "$memory" \
    --cores 1 \
    --execution-timeout "$timeout" \
    --min-instances "$STAND_MIN_INSTANCES" \
    --concurrency "${STAND_CONCURRENCY:-4}" \
    "$@" >/dev/null
  yc serverless container allow-unauthenticated-invoke --name "$name" >/dev/null
  url=$(yc serverless container get --name "$name" --format json | jq -r '.url')
  if [ -z "$url" ] || [ "$url" = "null" ]; then
    echo "Не получили url контейнера $name" >&2
    return 1
  fi
  printf '%s/\n' "${url%/}"
}

# wait_health URL — ждёт 200 и "status" в URL/health (холодный старт до 2 минут)
wait_health() {
  i=0
  until body=$(curl -fsS --max-time 30 "${1}health"); do
    i=$((i + 1))
    if [ "$i" -ge 12 ]; then
      echo "${1}health не ответил 200" >&2
      return 1
    fi
    sleep 10
  done
  case "$body" in
    *'"status"'*) echo "${1}health: ок" ;;
    *) echo "${1}health: нет status" >&2; return 1 ;;
  esac
}
