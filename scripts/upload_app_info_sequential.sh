#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"

SOURCE_METADATA_DIR="$REPO_ROOT/metadata"
ONE_LOCALE_METADATA_DIR="$PREPARED_DIR/one_locale_metadata"
DELAY_SECONDS="${APP_INFO_UPLOAD_DELAY_SECONDS:-5}"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

if [[ "${SKIP_PREPARE:-false}" != "true" ]]; then
  bash "$SCRIPT_DIR/prepare_metadata.sh"
fi

failed_locales=()
uploaded_locales=()
skipped_locales=()
candidate_locales=()

upload_locale() {
  local locale="$1"
  local source_locale_dir="$SOURCE_METADATA_DIR/$locale"
  local target_locale_dir="$ONE_LOCALE_METADATA_DIR/$locale"

  rm -rf "$ONE_LOCALE_METADATA_DIR"
  mkdir -p "$target_locale_dir"

  if [[ -s "$source_locale_dir/name.txt" ]]; then
    cp "$source_locale_dir/name.txt" "$target_locale_dir/name.txt"
  else
    echo "Skipping $locale: missing or empty name.txt"
    skipped_locales+=("$locale")
    return 0
  fi

  if [[ -s "$source_locale_dir/subtitle.txt" ]]; then
    cp "$source_locale_dir/subtitle.txt" "$target_locale_dir/subtitle.txt"
  fi

  echo "Uploading app name/subtitle for $locale..."
  if METADATA_PATH="$ONE_LOCALE_METADATA_DIR" run_fastlane ios upload_app_info_for_locale; then
    uploaded_locales+=("$locale")
    echo "Uploaded app info for $locale."
  else
    failed_locales+=("$locale")
    echo "WARNING: failed to upload app info for $locale. Continuing with next locale."
  fi
}

for locale_dir in "$SOURCE_METADATA_DIR"/*; do
  [[ -d "$locale_dir" ]] || continue
  locale="$(basename "$locale_dir")"
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
  echo "Skipped app info locale(s) (empty name): ${skipped_locales[*]}"
fi
if [[ "${#failed_locales[@]}" -gt 0 ]]; then
  echo "ERROR: Failed app info locale(s): ${failed_locales[*]}" >&2
  echo "Most common reason: App Store Connect rejected a non-unique app name." >&2
  report_warning "App info upload failed for ${#failed_locales[@]} locale(s): ${failed_locales[*]}"
  report_error "App info upload failed for ${#failed_locales[@]} locale(s): ${failed_locales[*]}"
  exit 1
fi
