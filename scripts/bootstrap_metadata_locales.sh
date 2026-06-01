#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$SCRIPT_DIR/load_account_config.sh"

python3 "$SCRIPT_DIR/bootstrap_metadata_locales.py"
