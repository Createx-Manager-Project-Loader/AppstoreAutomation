#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"

if [[ ! -d "$METADATA_DIR" ]]; then
  echo "Missing $METADATA_DIR"
  echo "Create locale folders first, or download existing metadata from App Store Connect."
  exit 1
fi

python3 "$SCRIPT_DIR/release_notes.py"
