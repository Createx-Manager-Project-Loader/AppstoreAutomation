#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
source "$(cd "$(dirname "$SCRIPT_PATH")" && pwd)/lib/paths.sh"

ACCOUNT_CONFIG_FILE="${ACCOUNT_CONFIG_FILE:-$REPO_ROOT/account.env}"

log_paths
log_info "Loading App Store Connect account config"

if [[ -f "$ACCOUNT_CONFIG_FILE" ]]; then
  log_debug "Sourcing account config: $ACCOUNT_CONFIG_FILE"
  set -a
  source "$ACCOUNT_CONFIG_FILE"
  set +a
else
  log_debug "Account config file not found: $ACCOUNT_CONFIG_FILE"
fi

ASC_KEY_ID="${ASC_KEY_ID:-${APPSTORE_CONNECT_API_KEY_ID:-}}"
ASC_ISSUER_ID="${ASC_ISSUER_ID:-${APPSTORE_CONNECT_API_ISSUER_ID:-}}"
APP_IDENTIFIER="${APP_IDENTIFIER:-${BUNDLE_IDENTIFIER:-}}"
ASC_PRIVATE_KEY="${ASC_PRIVATE_KEY:-${APPSTORE_CONNECT_API_PRIVATE_KEY:-}}"

: "${ASC_KEY_ID:?Missing ASC_KEY_ID or APPSTORE_CONNECT_API_KEY_ID}"
: "${ASC_ISSUER_ID:?Missing ASC_ISSUER_ID or APPSTORE_CONNECT_API_ISSUER_ID}"
: "${APP_IDENTIFIER:?Missing APP_IDENTIFIER or BUNDLE_IDENTIFIER}"

if [[ -n "${ASC_PRIVATE_KEY:-}" ]]; then
  GENERATED_KEY_DIR="$PREPARED_DIR/secrets"
  GENERATED_KEY_PATH="$GENERATED_KEY_DIR/AuthKey_${ASC_KEY_ID}.p8"
  mkdir -p "$GENERATED_KEY_DIR"
  printf '%s\n' "$ASC_PRIVATE_KEY" > "$GENERATED_KEY_PATH"
  chmod 600 "$GENERATED_KEY_PATH"
  ASC_KEY_PATH="$GENERATED_KEY_PATH"
elif [[ -n "${ASC_KEY_PATH:-}" ]]; then
  if [[ "$ASC_KEY_PATH" != /* ]]; then
    ASC_KEY_PATH="$REPO_ROOT/$ASC_KEY_PATH"
  fi
else
  echo "Missing ASC_KEY_PATH, ASC_PRIVATE_KEY, or APPSTORE_CONNECT_API_PRIVATE_KEY"
  exit 1
fi

if [[ ! -f "$ASC_KEY_PATH" ]]; then
  echo "Missing ASC key file: $ASC_KEY_PATH"
  exit 1
fi

export ASC_KEY_ID ASC_ISSUER_ID ASC_KEY_PATH APP_IDENTIFIER
log_info "App Store Connect target app: $APP_IDENTIFIER"
log_info "ASC key id: $ASC_KEY_ID"
log_info "ASC key path: $ASC_KEY_PATH"
