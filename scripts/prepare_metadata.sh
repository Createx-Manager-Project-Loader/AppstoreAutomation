#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"

python3 "$SCRIPT_DIR/prepare_metadata.py"
