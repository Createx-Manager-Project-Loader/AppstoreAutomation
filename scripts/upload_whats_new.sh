#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

bash "$SCRIPT_DIR/apply_release_notes_to_locales.sh"

locale_count=0
for locale_dir in "$METADATA_DIR"/*; do
  [[ -d "$locale_dir" ]] || continue
  [[ -s "$locale_dir/release_notes.txt" ]] || continue
  locale_count=$((locale_count + 1))
done

if ! run_fastlane ios update_whats_new; then
  report_merge whats_new upload_status=failed locales_total="$locale_count"
  report_error "What's New upload failed (fastlane deliver)."
  exit 1
fi

report_merge whats_new upload_status=success locales_total="$locale_count" release_notes_prepared="$locale_count"
echo "What's New upload completed for $locale_count locale(s)."
