#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"

log_step "prepare_metadata.sh"
status=0
python3 "$SCRIPT_DIR/prepare_metadata.py" || status=$?
log_step_done "prepare_metadata.sh" "$status"
exit "$status"
