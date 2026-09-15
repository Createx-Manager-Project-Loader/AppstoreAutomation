#!/usr/bin/env bash
# Первая заливка: карточка приложения, которого в сторе ещё нет.
#
# Порядок важен. Сначала раскладываются файлы из листинга — если в нём дыры,
# прогон останавливается здесь, до единого обращения к Apple. Потом deliver
# заливает тексты и скриншоты. И только после этого прямыми вызовами API
# доставляется то, до чего deliver не дотягивается: цена, страны, анкета
# рейтинга, права на контент, рекламный идентификатор.
#
# Последним шагом стоит setup_app.py не случайно: версия и карточка должны
# существовать, иначе править в них нечего.
set -euo pipefail

FIRST_RELEASE_SCRIPTS="$(cd "$(dirname "$0")/.." && pwd)"
source "$FIRST_RELEASE_SCRIPTS/lib/paths.sh"
# Раскладывает ключ из секрета в файл и выставляет ASC_KEY_ID / ASC_ISSUER_ID /
# ASC_KEY_PATH / APP_IDENTIFIER — те же имена, что у обычных прогонов.
source "$FIRST_RELEASE_SCRIPTS/load_account_config.sh"

FIRST_RELEASE_DIR="${FIRST_RELEASE_DIR:-$PREPARED_DIR/first-release}"
LISTING_PATH="${FIRST_RELEASE_LISTING:-$REPO_ROOT/app_store_listing.yml}"

if [[ ! -f "$LISTING_PATH" ]]; then
  log_error "Нет файла листинга: $LISTING_PATH"
  log_error "Его собирает разработчик скиллом setup-store-legal и приносит ПМ в консоль."
  exit 1
fi

log_step "Первая заливка"
log_info "Листинг: $LISTING_PATH"
log_info "Приложение: ${APP_IDENTIFIER:-<не задано>}"

# 1. Листинг → раскладка для deliver. Падает, если есть неподтверждённые поля.
log_step "Шаг 1/4: раскладка метаданных из листинга"
rm -rf "$FIRST_RELEASE_DIR"
python3 "$SCRIPT_DIR/first_release/build_metadata.py" "$LISTING_PATH" --out "$FIRST_RELEASE_DIR"

# 2. Скриншоты — тем же путём, что и в обычных прогонах: скачать по ссылке,
#    обязательно снять метаданные, разложить по локалям.
SCREENSHOTS_PATH=""
if [[ -n "${SCREENSHOTS_ZIP_URL:-}" ]]; then
  log_step "Шаг 2/4: скриншоты"
  python3 - <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.environ["SCRIPT_DIR"]))
from prepare_metadata import prepare_screenshots, PREPARED_SCREENSHOTS_DIR
prepare_screenshots()
print(f"Скриншоты разложены в {PREPARED_SCREENSHOTS_DIR}")
PY
  SCREENSHOTS_PATH="$PREPARED_DIR/screenshots"
else
  log_step "Шаг 2/4: скриншоты пропущены (SCREENSHOTS_ZIP_URL не задан)"
fi

# 3. deliver: тексты карточки, категории, контакты ревью, скриншоты.
log_step "Шаг 3/4: заливка карточки через deliver"
export FIRST_RELEASE_METADATA_PATH="$FIRST_RELEASE_DIR/metadata"
if [[ -n "$SCREENSHOTS_PATH" ]]; then
  export FIRST_RELEASE_SCREENSHOTS_PATH="$SCREENSHOTS_PATH"
fi
FIRST_RELEASE_RELEASE_TYPE="$(python3 - <<'PY'
import json, os, pathlib
path = pathlib.Path(os.environ["FIRST_RELEASE_METADATA_PATH"]).parent / "deliver_options.json"
print(json.loads(path.read_text()).get("release_type", ""))
PY
)"
export FIRST_RELEASE_RELEASE_TYPE
log_info "Способ релиза: ${FIRST_RELEASE_RELEASE_TYPE:-manual}"
run_fastlane first_release

# 4. То, чего в deliver нет. Каждое поле после записи читается обратно.
log_step "Шаг 4/4: цена, страны, рейтинг, права, IDFA"
python3 "$SCRIPT_DIR/first_release/setup_app.py" --listing "$LISTING_PATH"

log_info "Первая заливка завершена. Карточка заполнена, на ревью не отправлена."
