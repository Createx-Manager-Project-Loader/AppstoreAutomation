#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"

if [[ ! -d "$METADATA_DIR" ]]; then
  echo "Missing $METADATA_DIR"
  echo "Create locale folders first, or download existing metadata from App Store Connect."
  exit 1
fi

python3 "$SCRIPT_DIR/release_notes.py" || {
  existing_count=0
  for locale_dir in "$METADATA_DIR"/*; do
    [[ -d "$locale_dir" ]] || continue
    [[ -s "$locale_dir/release_notes.txt" ]] || continue
    existing_count=$((existing_count + 1))
  done
  if [[ "$existing_count" -gt 0 ]]; then
    echo "WARNING: release_notes.py failed; continuing with $existing_count existing release_notes.txt file(s)." >&2
    exit 0
  fi
  exit 1
}
