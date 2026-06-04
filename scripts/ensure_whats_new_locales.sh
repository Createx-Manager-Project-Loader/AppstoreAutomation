#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"

PREPARED_SCREENSHOTS_DIR="$PREPARED_DIR/screenshots"
LOCALE_PATTERN='^[a-z]{2}(-[A-Za-z]{2,4})?$'

screenshot_locale_added=0
if [[ -d "$PREPARED_SCREENSHOTS_DIR" ]]; then
  for locale_dir in "$PREPARED_SCREENSHOTS_DIR"/*; do
    [[ -d "$locale_dir" ]] || continue
    locale="$(basename "$locale_dir")"
    [[ "$locale" =~ $LOCALE_PATTERN ]] || continue
    mkdir -p "$METADATA_DIR/$locale"
    screenshot_locale_added=$((screenshot_locale_added + 1))
  done
fi

metadata_locale_count=0
for locale_dir in "$METADATA_DIR"/*; do
  [[ -d "$locale_dir" ]] || continue
  locale="$(basename "$locale_dir")"
  [[ "$locale" =~ $LOCALE_PATTERN ]] || continue
  metadata_locale_count=$((metadata_locale_count + 1))
done

if [[ "$metadata_locale_count" -gt 0 ]]; then
  if [[ "$screenshot_locale_added" -gt 0 ]]; then
    echo "Using metadata locale folders for What's New ($metadata_locale_count; ensured $screenshot_locale_added screenshot locale folder(s))."
    report_merge whats_new locales_total="$metadata_locale_count" bootstrap_source=existing_metadata_and_screenshots
  else
    echo "Using existing metadata locale folders for What's New ($metadata_locale_count)."
    report_merge whats_new locales_total="$metadata_locale_count" bootstrap_source=existing_metadata
  fi
  exit 0
fi

echo "No metadata or screenshot locales found. Creating locale folders from editable App Store version..."
export METADATA_DIR
if bash "$SCRIPT_DIR/bootstrap_metadata_locales.sh"; then
  metadata_locale_count=0
  for locale_dir in "$METADATA_DIR"/*; do
    [[ -d "$locale_dir" ]] || continue
    locale="$(basename "$locale_dir")"
    [[ "$locale" =~ $LOCALE_PATTERN ]] || continue
    metadata_locale_count=$((metadata_locale_count + 1))
  done
  if [[ "$metadata_locale_count" -gt 0 ]]; then
    report_merge whats_new locales_total="$metadata_locale_count" bootstrap_locales="$metadata_locale_count" bootstrap_source=editable_version
    exit 0
  fi
  echo "WARNING: bootstrap finished but no locale folders were found in $METADATA_DIR."
fi

echo "Could not bootstrap locales from editable version. Falling back to latest released App Store version..."
AUTOMATION_SCRIPTS_DIR="$SCRIPT_DIR" python3 - <<'PY'
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["AUTOMATION_SCRIPTS_DIR"])

from prepare_metadata import REPO_ROOT, get_release_notes_fallback
from release_notes import fetch_editable_release_note_locales, fetch_live_release_note_locales

metadata_dir = Path(os.environ.get("METADATA_DIR", str(REPO_ROOT / "metadata")))
locales = fetch_editable_release_note_locales(REPO_ROOT)
if not locales:
    locales = fetch_live_release_note_locales(REPO_ROOT)

if not locales and get_release_notes_fallback():
    locales = ["en-US"]

if not locales:
    print(
        "ERROR: No live App Store locales found and config release_notes is empty. "
        "Set release_notes in automation-config.yaml or make sure the app has a Ready for Sale version.",
        file=sys.stderr,
    )
    sys.exit(1)

for locale in locales:
    (metadata_dir / locale).mkdir(parents=True, exist_ok=True)

print(f"Created metadata locale folders from App Store Connect ({len(locales)}).")

sys.path.insert(0, os.environ["AUTOMATION_SCRIPTS_DIR"] + "/lib")
from automation_report import merge_section

merge_section(
    "whats_new",
    {
        "bootstrap_locales": len(locales),
        "bootstrap_source": "app_store_connect",
    },
)
PY
