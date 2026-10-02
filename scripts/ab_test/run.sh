#!/usr/bin/env bash
# Обвязка для A/B-теста: разложить ключ и позвать нужный скрипт.
#
# Без неё скрипты падают на «Missing required environment variable: ASC_KEY_ID».
# Секреты в репозитории названы APPSTORE_CONNECT_API_*, а скрипты ждут
# ASC_KEY_ID / ASC_ISSUER_ID / ASC_KEY_PATH / APP_IDENTIFIER, причём ключ им
# нужен файлом, а не строкой. Переименование и раскладку делает
# load_account_config.sh — тот же, что у обычных прогонов и у первой заливки.
set -euo pipefail

AB_SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$AB_SCRIPTS/.." && pwd)"
source "$SCRIPTS_DIR/lib/paths.sh"
source "$SCRIPTS_DIR/load_account_config.sh"

ACTION="${AB_ACTION:?не задано AB_ACTION}"
log_step "A/B-тест: $ACTION"

case "$ACTION" in
  sync)
    python3 "$AB_SCRIPTS/sync.py" --out "$PREPARED_DIR/ab-state.json"
    ;;

  upload)
    OVERWRITE=()
    [[ "${AB_OVERWRITE:-no}" == "yes" ]] && OVERWRITE=(--overwrite)
    python3 "$AB_SCRIPTS/upload.py" \
      --plan "${AB_PLAN:?не задан план}" \
      --out "$PREPARED_DIR/ab-result.json" \
      "${OVERWRITE[@]}"
    ;;

  edit|stop|start|delete|apply)
    ARGS=(--experiment "${AB_EXPERIMENT:?не задан тест}")
    [[ -n "${AB_TREATMENT:-}" ]] && ARGS+=(--treatment "$AB_TREATMENT")
    [[ -n "${AB_NAME:-}" ]] && ARGS+=(--name "$AB_NAME")
    [[ -n "${AB_TRAFFIC:-}" ]] && ARGS+=(--traffic "$AB_TRAFFIC")
    python3 "$AB_SCRIPTS/manage.py" "$ACTION" "${ARGS[@]}"
    ;;

  *)
    echo "ERROR: неизвестное действие «$ACTION»" >&2
    exit 1
    ;;
esac

# Состояние после любого изменения — консоль читает его из лога. У sync оно
# уже напечатано самим скриптом, второй раз незачем.
if [[ "$ACTION" != "sync" ]]; then
  log_step "Перечитываем состояние"
  python3 "$AB_SCRIPTS/sync.py" --out "$PREPARED_DIR/ab-state.json" || true
fi
