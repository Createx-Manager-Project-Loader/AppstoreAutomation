#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"

ONE_LOCALE_METADATA_DIR="$PREPARED_DIR/one_locale_whats_new"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

bash "$SCRIPT_DIR/apply_release_notes_to_locales.sh"

candidate_locales=()
uploaded_locales=()
failed_locales=()

for locale_dir in "$METADATA_DIR"/*; do
  [[ -d "$locale_dir" ]] || continue
  [[ -s "$locale_dir/release_notes.txt" ]] || continue
  candidate_locales+=("$(basename "$locale_dir")")
done

upload_locale() {
  local locale="$1"
  local source_locale_dir="$METADATA_DIR/$locale"
  local target_locale_dir="$ONE_LOCALE_METADATA_DIR/$locale"

  rm -rf "$ONE_LOCALE_METADATA_DIR"
  mkdir -p "$target_locale_dir"

  cp "$source_locale_dir/release_notes.txt" "$target_locale_dir/release_notes.txt"
  if [[ -s "$source_locale_dir/support_url.txt" ]]; then
    cp "$source_locale_dir/support_url.txt" "$target_locale_dir/support_url.txt"
  fi
  if [[ -s "$source_locale_dir/marketing_url.txt" ]]; then
    cp "$source_locale_dir/marketing_url.txt" "$target_locale_dir/marketing_url.txt"
  fi

  echo "Uploading What's New for $locale..."
  if METADATA_PATH="$ONE_LOCALE_METADATA_DIR" run_fastlane ios update_whats_new_for_locale; then
    uploaded_locales+=("$locale")
    echo "Uploaded What's New for $locale."
  else
    failed_locales+=("$locale")
    echo "WARNING: failed to upload What's New for $locale. Continuing with next locale." >&2
  fi
}

for locale in "${candidate_locales[@]}"; do
  upload_locale "$locale"
done

rm -rf "$ONE_LOCALE_METADATA_DIR"

locale_count="${#candidate_locales[@]}"
report_merge whats_new \
  locales_total="$locale_count" \
  release_notes_prepared="$locale_count" \
  uploaded="${#uploaded_locales[@]}" \
  failed="${#failed_locales[@]}" \
  uploaded_locales="${uploaded_locales[*]-}" \
  failed_locales="${failed_locales[*]-}"

echo "Sequential What's New upload completed: ${#uploaded_locales[@]} / $locale_count locale(s)."

if [[ "${#failed_locales[@]}" -gt 0 ]]; then
  report_merge whats_new upload_status=partial
  report_warning "What's New upload failed for ${#failed_locales[@]} locale(s): ${failed_locales[*]}"
  report_error "What's New upload failed for ${#failed_locales[@]} locale(s): ${failed_locales[*]}"
  exit 1
fi

report_merge whats_new upload_status=success
