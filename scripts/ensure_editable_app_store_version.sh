#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

python3 "$SCRIPT_DIR/ensure_editable_app_store_version.py"
