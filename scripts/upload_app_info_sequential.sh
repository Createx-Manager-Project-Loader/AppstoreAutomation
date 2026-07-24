#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"

SOURCE_METADATA_DIR="$REPO_ROOT/metadata"
ONE_LOCALE_METADATA_DIR="$PREPARED_DIR/one_locale_metadata"
DELAY_SECONDS="${APP_INFO_UPLOAD_DELAY_SECONDS:-5}"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

log_step "App name / subtitle upload"
if [[ "${SKIP_PREPARE:-false}" != "true" ]]; then
  bash "$SCRIPT_DIR/prepare_metadata.sh"
fi

failed_locales=()
uploaded_locales=()
skipped_locales=()
candidate_locales=()

prepare_locale_dir() {
  local locale="$1"
  local include_name="${2:-false}"
  local include_subtitle="${3:-false}"
  local source_locale_dir="$SOURCE_METADATA_DIR/$locale"
  local target_locale_dir="$ONE_LOCALE_METADATA_DIR/$locale"

  rm -rf "$ONE_LOCALE_METADATA_DIR"
  mkdir -p "$target_locale_dir"

  if [[ "$include_name" == "true" && -s "$source_locale_dir/name.txt" ]]; then
    cp "$source_locale_dir/name.txt" "$target_locale_dir/name.txt"
  fi

  if [[ "$include_subtitle" == "true" && -s "$source_locale_dir/subtitle.txt" ]]; then
    cp "$source_locale_dir/subtitle.txt" "$target_locale_dir/subtitle.txt"
  fi
}

upload_locale() {
  local locale="$1"
  local source_locale_dir="$SOURCE_METADATA_DIR/$locale"
  local has_name=false
  local has_subtitle=false
  local lane="upload_app_info_for_locale"

  [[ "$APP_INFO_WANT_NAME" == "true" && -s "$source_locale_dir/name.txt" ]] && has_name=true
  [[ "$APP_INFO_WANT_SUBTITLE" == "true" && -s "$source_locale_dir/subtitle.txt" ]] && has_subtitle=true

  if [[ "$has_name" == "false" && "$has_subtitle" == "false" ]]; then
    echo "Skipping $locale: missing name.txt and subtitle.txt"
    skipped_locales+=("$locale")
    return 0
  fi

  local safe_locale="${locale//[^A-Za-z0-9_.-]/_}"
  AUTOMATION_FASTLANE_LOG="$PREPARED_DIR/fastlane_app_info_${safe_locale}.log"

  if [[ "$has_name" == "true" && "$has_subtitle" == "true" ]]; then
    prepare_locale_dir "$locale" true true
    log_step "App info upload: $locale (name + subtitle)"
  elif [[ "$has_subtitle" == "true" ]]; then
    prepare_locale_dir "$locale" false true
    lane="upload_app_subtitle_for_locale"
    log_step "App info upload: $locale (subtitle only)"
  else
    prepare_locale_dir "$locale" true false
    log_step "App info upload: $locale (name only)"
  fi

  log_locale_dir_summary "$ONE_LOCALE_METADATA_DIR/$locale"
  log_info "Fastlane lane: ios $lane"

  local log_file="$AUTOMATION_FASTLANE_LOG"
  local included_name_flag=false
  [[ "$has_name" == "true" ]] && included_name_flag=true

  if METADATA_PATH="$ONE_LOCALE_METADATA_DIR" run_fastlane ios "$lane"; then
    uploaded_locales+=("$locale")
    log_info "Uploaded app info for $locale."
    log_step_done "App info upload: $locale" 0
  else
    failed_locales+=("$locale")
    report_locale_failure app_info "$locale" app_info 1 "$log_file" "$included_name_flag" >/dev/null
    log_warn "Failed to upload app info for $locale. Continuing with next locale."
    log_step_done "App info upload: $locale" 1
  fi
  unset AUTOMATION_FASTLANE_LOG
}

# Точный выбор полей: app_info владеет name и subtitle. Пусто = оба, как раньше.
APP_INFO_WANT_NAME=true
APP_INFO_WANT_SUBTITLE=true
if [[ -n "${ASC_METADATA_ITEMS:-}" ]]; then
  APP_INFO_WANT_NAME=false
  APP_INFO_WANT_SUBTITLE=false
  IFS=',' read -ra _items <<<"${ASC_METADATA_ITEMS}"
  for _it in "${_items[@]}"; do
    _it="${_it//[[:space:]]/}"
    [[ "$_it" == "name" ]] && APP_INFO_WANT_NAME=true
    [[ "$_it" == "subtitle" ]] && APP_INFO_WANT_SUBTITLE=true
  done
fi

if [[ "$APP_INFO_WANT_NAME" == "false" && "$APP_INFO_WANT_SUBTITLE" == "false" ]]; then
  echo "Neither name nor subtitle selected in ASC_METADATA_ITEMS; skipping app info upload."
  report_merge app_info skipped=true status=skipped reason=no_requested_items
  exit 0
fi

for locale_dir in "$SOURCE_METADATA_DIR"/*; do
  [[ -d "$locale_dir" ]] || continue
  locale="$(basename "$locale_dir")"
  locale_selected "$locale" || continue
  [[ -f "$locale_dir/name.txt" || -f "$locale_dir/subtitle.txt" ]] || continue
  candidate_locales+=("$locale")
  upload_locale "$locale"
  sleep "$DELAY_SECONDS"
done

rm -rf "$ONE_LOCALE_METADATA_DIR"

total_locales="${#candidate_locales[@]}"
if [[ "$total_locales" -eq 0 ]]; then
  echo "No app info locales found in $SOURCE_METADATA_DIR (no locale folders with name.txt or subtitle.txt)."
fi

uploaded_locale_list="${uploaded_locales[*]-}"
failed_locale_list="${failed_locales[*]-}"

report_merge app_info \
  total="$total_locales" \
  uploaded="${#uploaded_locales[@]}" \
  failed="${#failed_locales[@]}" \
  skipped_locales="${#skipped_locales[@]}" \
  uploaded_locales="$uploaded_locale_list" \
  failed_locales="$failed_locale_list"

echo "Uploaded app info locale(s): ${uploaded_locales[*]:-none} (${#uploaded_locales[@]} / $total_locales)"
if [[ "${#skipped_locales[@]}" -gt 0 ]]; then
  echo "Skipped app info locale(s) (empty name and subtitle): ${skipped_locales[*]}"
fi
if [[ "${#failed_locales[@]}" -gt 0 ]]; then
  echo "ERROR: Failed app info locale(s): ${failed_locales[*]}" >&2
  echo "Most common reason: App Store Connect rejected a non-unique app name." >&2
  report_warning "App info upload failed for ${#failed_locales[@]} locale(s): ${failed_locales[*]}"
  report_error "App info upload failed for ${#failed_locales[@]} locale(s): ${failed_locales[*]}"
  report_merge app_info status=partial
  echo "Uploaded ${#uploaded_locales[@]} / $total_locales app info locale(s) before failures."
  exit 1
fi
