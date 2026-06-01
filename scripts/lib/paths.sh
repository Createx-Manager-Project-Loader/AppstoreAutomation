#!/usr/bin/env bash

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$(cd "$LIB_DIR/.." && pwd)"
AUTOMATION_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$AUTOMATION_DIR/.." && pwd)"
METADATA_DIR="$REPO_ROOT/metadata"

if [[ -n "${AUTOMATION_CONFIG_PATH:-}" ]]; then
  CONFIG_PATH="$AUTOMATION_CONFIG_PATH"
else
  CONFIG_PATH="$REPO_ROOT/automation-config.yaml"
fi

if [[ -n "${AUTOMATION_PREPARED_DIR:-}" ]]; then
  PREPARED_DIR="$AUTOMATION_PREPARED_DIR"
else
  PREPARED_DIR="$REPO_ROOT/automation-prepared"
fi

export LIB_DIR SCRIPT_DIR AUTOMATION_DIR REPO_ROOT PREPARED_DIR CONFIG_PATH METADATA_DIR

run_fastlane() {
  (
    cd "$AUTOMATION_DIR"
    if [[ -f "Gemfile" ]]; then
      bundle exec fastlane "$@"
    else
      fastlane "$@"
    fi
  )
}
