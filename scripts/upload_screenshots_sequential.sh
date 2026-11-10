#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"

PREPARED_SCREENSHOTS_DIR="$PREPARED_DIR/screenshots"
ONE_LOCALE_DIR="$PREPARED_DIR/one_locale_screenshots"
# Языки заливаются без ожидания обработки у Apple; порядок кадров ставит один
# общий проход в конце (upload_screenshots_api.py --finalize), когда Apple
# обработал наборы. Раньше каждый язык ждал до 5 минут и перезаливался по кругу.
ORDER_MANIFEST="$PREPARED_DIR/screenshot_order_manifest.jsonl"
ORDER_RESULT="$PREPARED_DIR/screenshot_order_result.json"
DELAY_SECONDS="${SCREENSHOT_UPLOAD_DELAY_SECONDS:-0}"
RETRY_DELAY_SECONDS="${SCREENSHOT_UPLOAD_RETRY_DELAY_SECONDS:-5}"
MAX_ATTEMPTS="${SCREENSHOT_UPLOAD_MAX_ATTEMPTS:-5}"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

log_step "Screenshot upload"
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
  locale_selected "$(basename "$locale_dir")" || continue
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
rm -f "$ORDER_MANIFEST" "$ORDER_RESULT"

run_api_upload() {
  local locale="$1"
  local attempt="$2"
  local safe_locale="${locale//[^A-Za-z0-9_.-]/_}"
  local log_file="$PREPARED_DIR/api_screenshots_${safe_locale}_attempt_${attempt}.log"

  rm -f "$log_file"
  python3 "$SCRIPT_DIR/upload_screenshots_api.py" \
    --locale "$locale" \
    --screenshots-path "$ONE_LOCALE_DIR" \
    --order-manifest "$ORDER_MANIFEST" \
    > >(tee "$log_file") \
    2> >(tee -a "$log_file" >&2)
}

upload_locale() {
  local locale="$1"
  local attempt=1
  local safe_locale="${locale//[^A-Za-z0-9_.-]/_}"
  local last_log_file=""

  rm -rf "$ONE_LOCALE_DIR"
  mkdir -p "$ONE_LOCALE_DIR"
  cp -R "$PREPARED_SCREENSHOTS_DIR/$locale" "$ONE_LOCALE_DIR/$locale"

  log_step "Screenshot upload: $locale"
  log_debug "Screenshot source: $PREPARED_SCREENSHOTS_DIR/$locale"

  while true; do
    last_log_file="$PREPARED_DIR/api_screenshots_${safe_locale}_attempt_${attempt}.log"
    log_info "Uploading screenshots for $locale (attempt $attempt/$MAX_ATTEMPTS)..."
    if run_api_upload "$locale" "$attempt"; then
      log_info "Uploaded screenshots for $locale."
      uploaded_locales+=("$locale")
      log_step_done "Screenshot upload: $locale" 0
      break
    fi

    if [[ "$attempt" -ge "$MAX_ATTEMPTS" ]]; then
      failed_locales+=("$locale")
      report_locale_failure screenshots "$locale" screenshots 1 "$last_log_file" >/dev/null
      log_warn "Failed to upload screenshots for $locale after $MAX_ATTEMPTS attempt(s). Continuing with next locale."
      log_step_done "Screenshot upload: $locale" 1
      break
    fi

    attempt=$((attempt + 1))
    log_warn "Retrying $locale after $RETRY_DELAY_SECONDS second(s)..."
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

# Порядок кадров: ждём обработку всех залитых наборов разом, ставим и сверяем.
# Не встал или Apple не дообработал — язык в ошибки, но наборы не трогаем.
if [[ "${#uploaded_locales[@]}" -gt 0 ]]; then
  order_log="$PREPARED_DIR/api_screenshots_order.log"
  rm -f "$order_log"
  python3 "$SCRIPT_DIR/upload_screenshots_api.py" \
    --finalize "$ORDER_MANIFEST" \
    --result "$ORDER_RESULT" \
    > >(tee "$order_log") \
    2> >(tee -a "$order_log" >&2) || true

  order_bad=()
  if [[ -f "$ORDER_RESULT" ]]; then
    while IFS= read -r locale; do
      [[ -n "$locale" ]] && order_bad+=("$locale")
    done < <(python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print("\n".join(sorted(set(r["failed"]) | set(r["unfinished"]))))' "$ORDER_RESULT")
  else
    # Проход не дошёл до итога (упал до запросов) — порядок не проверен ни у кого.
    order_bad=("${uploaded_locales[@]}")
  fi

  if [[ "${#order_bad[@]}" -gt 0 ]]; then
    kept=()
    for locale in "${uploaded_locales[@]}"; do
      if [[ " ${order_bad[*]} " == *" $locale "* ]]; then
        failed_locales+=("$locale")
        report_locale_failure screenshots "$locale" screenshots 1 "$order_log" >/dev/null
      else
        kept+=("$locale")
      fi
    done
    uploaded_locales=("${kept[@]+"${kept[@]}"}")
    report_warning "Screenshot order not confirmed for ${#order_bad[@]} locale(s): ${order_bad[*]}"
  fi
fi

report_merge screenshots \
  total="$total_locales" \
  uploaded="${#uploaded_locales[@]}" \
  failed="${#failed_locales[@]}" \
  uploaded_locales="${uploaded_locales[*]-}" \
  failed_locales="${failed_locales[*]-}"

echo "Sequential screenshot upload completed: ${#uploaded_locales[@]} / $total_locales locale(s)."

if [[ "${#failed_locales[@]}" -gt 0 ]]; then
  report_warning "Screenshot upload failed for ${#failed_locales[@]} locale(s): ${failed_locales[*]}"
  report_error "Screenshot upload failed for ${#failed_locales[@]} locale(s): ${failed_locales[*]}"
  report_merge screenshots status=partial
  exit 1
fi
