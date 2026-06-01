#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

if [[ "${SKIP_PREPARE:-false}" != "true" ]]; then
  bash "$SCRIPT_DIR/prepare_metadata.sh"
fi

if [[ ! -f "$PREPARED_DIR/subscription_localizations.json" ]]; then
  echo "No prepared subscription localizations. Skipping subscription upload."
  report_merge subscriptions skipped=true reason=no_prepared_data
  exit 0
fi

python3 "$SCRIPT_DIR/upload_subscriptions.py"
