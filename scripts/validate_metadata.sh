#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"

log_step "validate_metadata.sh"
python3 "$SCRIPT_DIR/validate_metadata.py"
status=$?
log_step_done "validate_metadata.sh" "$status"
exit "$status"
