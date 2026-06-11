#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"
source "$LIB_DIR/upload_continue.sh"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

metadata_locale_count=0
for locale_dir in "$METADATA_DIR"/*; do
  [[ -d "$locale_dir" ]] || continue
  locale="$(basename "$locale_dir")"
  [[ "$locale" =~ ^[a-z]{2}(-[A-Za-z]{2,4})?$ ]] || continue
  metadata_locale_count=$((metadata_locale_count + 1))
done

if [[ "$metadata_locale_count" -eq 0 ]]; then
  report_continue_step "What's New locale bootstrap" bash "$SCRIPT_DIR/ensure_whats_new_locales.sh"
fi

echo "Validating What's New inputs..."
report_continue_step "What's New validation" env WHATS_NEW_VALIDATE_ONLY=true bash "$SCRIPT_DIR/validate_metadata.sh"

echo "Ensuring editable App Store version exists..."
report_continue_step "Editable App Store version" bash "$SCRIPT_DIR/ensure_editable_app_store_version.sh"

report_continue_step "What's New apply + upload" bash "$SCRIPT_DIR/upload_whats_new.sh"
