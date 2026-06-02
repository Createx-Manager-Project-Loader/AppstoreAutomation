#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"

cd "$REPO_ROOT"
source "$SCRIPT_DIR/load_account_config.sh"

FASTLANE_METADATA_TIMEOUT_SECONDS="${FASTLANE_METADATA_TIMEOUT_SECONDS:-120}"
FASTLANE_METADATA_MAX_ATTEMPTS="${FASTLANE_METADATA_MAX_ATTEMPTS:-3}"
FASTLANE_METADATA_RETRY_DELAY_SECONDS="${FASTLANE_METADATA_RETRY_DELAY_SECONDS:-10}"
FASTLANE_METADATA_HEARTBEAT_SECONDS="${FASTLANE_METADATA_HEARTBEAT_SECONDS:-30}"

if [[ "${SKIP_PREPARE:-false}" != "true" ]]; then
  bash "$SCRIPT_DIR/prepare_metadata.sh"
  bash "$SCRIPT_DIR/validate_metadata.sh"
fi

run_with_timeout() {
  local timeout_seconds="$1"
  shift
  local pid
  local start_time
  local elapsed
  local next_heartbeat

  "$@" &
  pid=$!
  start_time="$(date +%s)"
  next_heartbeat="$FASTLANE_METADATA_HEARTBEAT_SECONDS"

  while kill -0 "$pid" 2>/dev/null; do
    elapsed=$(($(date +%s) - start_time))
    if [[ "$elapsed" -ge "$next_heartbeat" ]]; then
      echo "Fastlane metadata upload still running after $elapsed second(s); timeout is ${timeout_seconds}s."
      next_heartbeat=$((next_heartbeat + FASTLANE_METADATA_HEARTBEAT_SECONDS))
    fi

    if [[ "$elapsed" -ge "$timeout_seconds" ]]; then
      echo "Fastlane metadata upload timed out after $timeout_seconds second(s); stopping it."
      kill "$pid" 2>/dev/null || true
      sleep 2
      kill -9 "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 124
    fi
    sleep 5
  done

  wait "$pid"
}

upload_metadata_with_retries() {
  local attempt=1
  local status

  while true; do
    echo "Uploading metadata with fastlane (attempt $attempt/$FASTLANE_METADATA_MAX_ATTEMPTS, timeout ${FASTLANE_METADATA_TIMEOUT_SECONDS}s)..."
    set +e
    ASC_METADATA_ITEMS="$METADATA_ITEMS" \
      run_with_timeout "$FASTLANE_METADATA_TIMEOUT_SECONDS" \
      run_fastlane ios upload_metadata
    status=$?
    set -e

    if [[ "$status" -eq 0 ]]; then
      return 0
    fi

    echo "ERROR: fastlane metadata upload failed with exit code $status (attempt $attempt/$FASTLANE_METADATA_MAX_ATTEMPTS)." >&2

    if [[ "$attempt" -ge "$FASTLANE_METADATA_MAX_ATTEMPTS" ]]; then
      echo "Failed to upload metadata after $FASTLANE_METADATA_MAX_ATTEMPTS attempt(s)."
      report_merge metadata_upload status=failed error="fastlane exited with code $status"
      report_error "Metadata upload failed after $FASTLANE_METADATA_MAX_ATTEMPTS attempt(s)."
      return "$status"
    fi

    attempt=$((attempt + 1))
    echo "Retrying metadata upload after $FASTLANE_METADATA_RETRY_DELAY_SECONDS second(s)..."
    sleep "$FASTLANE_METADATA_RETRY_DELAY_SECONDS"
  done
}

has_description_metadata() {
  compgen -G "$REPO_ROOT/metadata/*/description.txt" >/dev/null
}

METADATA_ITEMS="subtitle,keywords"
if has_description_metadata; then
  METADATA_ITEMS="subtitle,keywords,description"
fi

if [[ "${RUN_WHATS_NEW:-false}" != "true" ]]; then
  METADATA_ITEMS="$METADATA_ITEMS,release_notes"
  if compgen -G "$REPO_ROOT/metadata/*/support_url.txt" >/dev/null; then
    METADATA_ITEMS="$METADATA_ITEMS,support_url"
  fi

  if compgen -G "$REPO_ROOT/metadata/*/marketing_url.txt" >/dev/null; then
    METADATA_ITEMS="$METADATA_ITEMS,marketing_url"
  fi
fi

if [[ "${INCLUDE_APP_NAME:-false}" == "true" ]]; then
  METADATA_ITEMS="name,$METADATA_ITEMS"
fi

ASC_METADATA_ITEMS="$METADATA_ITEMS" python3 "$SCRIPT_DIR/build_upload_metadata.py"
echo "Metadata upload items selected: $METADATA_ITEMS"

prepared_locale_count=0
if [[ -d "$PREPARED_DIR/metadata" ]]; then
  for locale_dir in "$PREPARED_DIR/metadata"/*; do
    [[ -d "$locale_dir" ]] || continue
    prepared_locale_count=$((prepared_locale_count + 1))
  done
fi

metadata_upload_status=0
upload_metadata_with_retries || metadata_upload_status=$?
if [[ "$metadata_upload_status" -ne 0 ]]; then
  report_merge metadata_upload status=failed error="fastlane exited with code $metadata_upload_status"
  report_error "Metadata upload failed with exit code $metadata_upload_status."
  exit "$metadata_upload_status"
fi

report_merge metadata_upload status=success locales="$prepared_locale_count" items="$METADATA_ITEMS"
echo "Metadata upload completed for $prepared_locale_count locale(s): $METADATA_ITEMS"
