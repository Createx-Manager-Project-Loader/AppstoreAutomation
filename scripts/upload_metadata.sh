#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

FASTLANE_METADATA_TIMEOUT_SECONDS="${FASTLANE_METADATA_TIMEOUT_SECONDS:-120}"
FASTLANE_METADATA_HEARTBEAT_SECONDS="${FASTLANE_METADATA_HEARTBEAT_SECONDS:-30}"
PREPARED_METADATA_DIR="$PREPARED_DIR/metadata"
ONE_LOCALE_METADATA_DIR="$PREPARED_DIR/one_locale_upload_metadata"

if [[ "${SKIP_PREPARE:-false}" != "true" ]]; then
  bash "$SCRIPT_DIR/prepare_metadata.sh"
  bash "$SCRIPT_DIR/validate_metadata.sh"
fi

run_with_timeout() {
  local timeout_seconds="$1"
  shift
  local pid
  local start_time
  local elapsed
  local next_heartbeat

  "$@" &
  pid=$!
  start_time="$(date +%s)"
  next_heartbeat="$FASTLANE_METADATA_HEARTBEAT_SECONDS"

  while kill -0 "$pid" 2>/dev/null; do
    elapsed=$(($(date +%s) - start_time))
    if [[ "$elapsed" -ge "$next_heartbeat" ]]; then
      echo "Fastlane metadata upload still running after $elapsed second(s); timeout is ${timeout_seconds}s."
      next_heartbeat=$((next_heartbeat + FASTLANE_METADATA_HEARTBEAT_SECONDS))
    fi

    if [[ "$elapsed" -ge "$timeout_seconds" ]]; then
      echo "Fastlane metadata upload timed out after $timeout_seconds second(s); stopping it."
      kill "$pid" 2>/dev/null || true
      sleep 2
      kill -9 "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 124
    fi
    sleep 5
  done

  wait "$pid"
}

upload_locale_metadata() {
  local locale="$1"
  local source_locale_dir="$PREPARED_METADATA_DIR/$locale"
  local target_locale_dir="$ONE_LOCALE_METADATA_DIR/$locale"
  local status

  rm -rf "$ONE_LOCALE_METADATA_DIR"
  mkdir -p "$target_locale_dir"
  cp -R "$source_locale_dir/." "$target_locale_dir/"

  local safe_locale="${locale//[^A-Za-z0-9_.-]/_}"
  AUTOMATION_FASTLANE_LOG="$PREPARED_DIR/fastlane_metadata_${safe_locale}.log"

  log_step "Metadata upload: $locale"
  log_locale_dir_summary "$target_locale_dir"
  log_info "Uploading metadata for $locale (items: $METADATA_ITEMS, timeout ${FASTLANE_METADATA_TIMEOUT_SECONDS}s)..."
  set +e
  ASC_METADATA_ITEMS="$METADATA_ITEMS" \
    METADATA_PATH="$ONE_LOCALE_METADATA_DIR" \
    run_with_timeout "$FASTLANE_METADATA_TIMEOUT_SECONDS" \
    run_fastlane ios upload_metadata_for_locale
  status=$?
  set -e

  local log_file="$AUTOMATION_FASTLANE_LOG"
  unset AUTOMATION_FASTLANE_LOG

  if [[ "$status" -eq 0 ]]; then
    uploaded_locales+=("$locale")
    log_info "Uploaded metadata for $locale."
    log_step_done "Metadata upload: $locale" 0
  else
    failed_locales+=("$locale")
    report_locale_failure metadata_upload "$locale" metadata "$status" "$log_file" >/dev/null
    log_warn "Failed to upload metadata for $locale (exit $status). Continuing with next locale."
    log_step_done "Metadata upload: $locale" "$status"
  fi
}

has_description_metadata() {
  compgen -G "$REPO_ROOT/metadata/*/description.txt" >/dev/null
}

# Автоматически определяем, какие поля вообще доступны (есть файлы + гейт whats_new).
AUTO_ITEMS="subtitle,keywords"
if has_description_metadata; then
  AUTO_ITEMS="subtitle,keywords,description"
fi

if compgen -G "$REPO_ROOT/metadata/*/promotional_text.txt" >/dev/null; then
  AUTO_ITEMS="$AUTO_ITEMS,promotional_text"
fi

if [[ "${RUN_WHATS_NEW:-false}" != "true" ]]; then
  AUTO_ITEMS="$AUTO_ITEMS,release_notes"
  if compgen -G "$REPO_ROOT/metadata/*/support_url.txt" >/dev/null; then
    AUTO_ITEMS="$AUTO_ITEMS,support_url"
  fi

  if compgen -G "$REPO_ROOT/metadata/*/marketing_url.txt" >/dev/null; then
    AUTO_ITEMS="$AUTO_ITEMS,marketing_url"
  fi
fi

if [[ "${INCLUDE_APP_NAME:-false}" == "true" ]]; then
  AUTO_ITEMS="name,$AUTO_ITEMS"
fi

# Если задан точный список полей (ASC_METADATA_ITEMS) — заливаем только выбранное
# И доступное (пересечение). Пусто → всё доступное, как раньше.
REQUESTED_ITEMS="${ASC_METADATA_ITEMS:-}"
if [[ -n "$REQUESTED_ITEMS" ]]; then
  METADATA_ITEMS=""
  IFS=',' read -ra _requested <<<"$REQUESTED_ITEMS"
  for _item in "${_requested[@]}"; do
    _item="${_item//[[:space:]]/}"
    [[ -z "$_item" ]] && continue
    if [[ ",$AUTO_ITEMS," == *",$_item,"* ]]; then
      METADATA_ITEMS="${METADATA_ITEMS:+$METADATA_ITEMS,}$_item"
    fi
  done
  log_info "Requested metadata items: $REQUESTED_ITEMS; available: $AUTO_ITEMS"
else
  METADATA_ITEMS="$AUTO_ITEMS"
fi

# Ничего из выбранного не доступно — пропускаем шаг, а не заливаем всё подряд.
if [[ -z "$METADATA_ITEMS" ]]; then
  echo "No requested metadata items available (requested: $REQUESTED_ITEMS). Skipping metadata upload."
  report_merge metadata_upload skipped=true status=skipped reason=no_requested_items
  exit 0
fi

log_step "Metadata upload"
ASC_METADATA_ITEMS="$METADATA_ITEMS" python3 "$SCRIPT_DIR/build_upload_metadata.py"
log_info "Metadata upload items selected: $METADATA_ITEMS"

candidate_locales=()
uploaded_locales=()
failed_locales=()

if [[ -d "$PREPARED_METADATA_DIR" ]]; then
  for locale_dir in "$PREPARED_METADATA_DIR"/*; do
    [[ -d "$locale_dir" ]] || continue
    locale_selected "$(basename "$locale_dir")" || continue
    candidate_locales+=("$(basename "$locale_dir")")
  done
fi

total_locales="${#candidate_locales[@]}"
if [[ "$total_locales" -eq 0 ]]; then
  echo "No metadata locales found in $PREPARED_METADATA_DIR."
fi

for locale in "${candidate_locales[@]}"; do
  upload_locale_metadata "$locale"
done

rm -rf "$ONE_LOCALE_METADATA_DIR"

report_merge metadata_upload \
  total="$total_locales" \
  uploaded="${#uploaded_locales[@]}" \
  failed="${#failed_locales[@]}" \
  locales="${#uploaded_locales[@]}" \
  items="$METADATA_ITEMS" \
  uploaded_locales="${uploaded_locales[*]-}" \
  failed_locales="${failed_locales[*]-}"

echo "Sequential metadata upload completed: ${#uploaded_locales[@]} / $total_locales locale(s): $METADATA_ITEMS"

if [[ "${#failed_locales[@]}" -gt 0 ]]; then
  echo "ERROR: Failed metadata locale(s): ${failed_locales[*]}" >&2
  report_warning "Metadata upload failed for ${#failed_locales[@]} locale(s): ${failed_locales[*]}"
  report_error "Metadata upload failed for ${#failed_locales[@]} locale(s): ${failed_locales[*]}"
  report_merge metadata_upload status=partial
  exit 1
fi

report_merge metadata_upload status=success
