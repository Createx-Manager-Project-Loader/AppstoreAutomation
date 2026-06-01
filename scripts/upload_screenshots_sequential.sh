#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"

PREPARED_SCREENSHOTS_DIR="$PREPARED_DIR/screenshots"
ONE_LOCALE_DIR="$PREPARED_DIR/one_locale_screenshots"
DELAY_SECONDS="${SCREENSHOT_UPLOAD_DELAY_SECONDS:-0}"
RETRY_DELAY_SECONDS="${SCREENSHOT_UPLOAD_RETRY_DELAY_SECONDS:-5}"
MAX_ATTEMPTS="${SCREENSHOT_UPLOAD_MAX_ATTEMPTS:-5}"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

if [[ "${SKIP_PREPARE:-false}" != "true" ]]; then
  bash "$SCRIPT_DIR/prepare_metadata.sh"
fi

if [[ ! -d "$PREPARED_SCREENSHOTS_DIR" ]]; then
  echo "Missing $PREPARED_SCREENSHOTS_DIR"
  exit 1
fi

screenshot_locales=()
for locale_dir in "$PREPARED_SCREENSHOTS_DIR"/*; do
  [[ -d "$locale_dir" ]] || continue
  screenshot_locales+=("$(basename "$locale_dir")")
done

total_locales="${#screenshot_locales[@]}"
if [[ "$total_locales" -eq 0 ]]; then
  echo "ERROR: No screenshot locale folders found in $PREPARED_SCREENSHOTS_DIR." >&2
  report_error "No screenshot locales prepared for upload."
  exit 1
fi

uploaded_locales=()
failed_locales=()

run_api_upload() {
  local locale="$1"
  local attempt="$2"
  local safe_locale="${locale//[^A-Za-z0-9_.-]/_}"
  local log_file="$PREPARED_DIR/api_screenshots_${safe_locale}_attempt_${attempt}.log"

  rm -f "$log_file"
  python3 "$SCRIPT_DIR/upload_screenshots_api.py" \
    --locale "$locale" \
    --screenshots-path "$ONE_LOCALE_DIR" \
    > >(tee "$log_file") \
    2> >(tee -a "$log_file" >&2)
}

upload_locale() {
  local locale="$1"
  local attempt=1

  rm -rf "$ONE_LOCALE_DIR"
  mkdir -p "$ONE_LOCALE_DIR"
  cp -R "$PREPARED_SCREENSHOTS_DIR/$locale" "$ONE_LOCALE_DIR/$locale"

  while true; do
    echo "Uploading screenshots for $locale (attempt $attempt/$MAX_ATTEMPTS)..."
    if run_api_upload "$locale" "$attempt"; then
      echo "Uploaded screenshots for $locale."
      uploaded_locales+=("$locale")
      break
    fi

    if [[ "$attempt" -ge "$MAX_ATTEMPTS" ]]; then
      echo "Failed to upload screenshots for $locale after $MAX_ATTEMPTS attempt(s)."
      failed_locales+=("$locale")
      report_merge screenshots \
        uploaded="${#uploaded_locales[@]}" \
        total="$total_locales" \
        failed="${#failed_locales[@]}" \
        failed_locales="${failed_locales[*]}"
      report_error "Screenshot upload failed for locale(s): ${failed_locales[*]}"
      exit 1
    fi

    attempt=$((attempt + 1))
    echo "Retrying $locale after $RETRY_DELAY_SECONDS second(s)..."
    sleep "$RETRY_DELAY_SECONDS"
  done
}

for locale in "${screenshot_locales[@]}"; do
  upload_locale "$locale"
  if [[ "$DELAY_SECONDS" -gt 0 ]]; then
    echo "Waiting $DELAY_SECONDS second(s) before next locale..."
    sleep "$DELAY_SECONDS"
  fi
done

rm -rf "$ONE_LOCALE_DIR"

report_merge screenshots \
  total="$total_locales" \
  uploaded="${#uploaded_locales[@]}" \
  failed="${#failed_locales[@]}" \
  uploaded_locales="${uploaded_locales[*]}" \
  failed_locales="${failed_locales[*]-}"

echo "Sequential screenshot upload completed: ${#uploaded_locales[@]} / $total_locales locale(s)."
