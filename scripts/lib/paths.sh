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

# shellcheck source=lib/log.sh
source "$LIB_DIR/log.sh"

run_fastlane() {
  local status=0
  local log_file="${AUTOMATION_FASTLANE_LOG:-}"
  local -a fastlane_args=()

  if [[ "${AUTOMATION_FASTLANE_VERBOSE:-}" == "1" ]]; then
    fastlane_args+=(--verbose)
  fi

  log_info "Fastlane start: $*"
  log_info "APP_IDENTIFIER=${APP_IDENTIFIER:-}"
  log_info "ASC_METADATA_ITEMS=${ASC_METADATA_ITEMS:-}"
  log_info "METADATA_PATH=${METADATA_PATH:-}"

  (
    cd "$AUTOMATION_DIR"
    export FASTLANE_DISABLE_COLORS=1
    export DELIVER_FORCE_OVERWRITE=1
    export FASTLANE_IS_INTERACTIVE=false
    export FASTLANE_SKIP_UPDATE_CHECK=1
    export FASTLANE_HIDE_ACTION_SUMMARY=1
    if [[ "${GITHUB_ACTIONS:-}" == "true" || "${CI:-}" == "true" ]]; then
      export CI=true
    fi

    run_fastlane_cmd() {
      if [[ -f "Gemfile" ]]; then
        bundle exec fastlane "${fastlane_args[@]}" "$@"
      else
        fastlane "${fastlane_args[@]}" "$@"
      fi
    }

    if [[ -n "$log_file" ]]; then
      mkdir -p "$(dirname "$log_file")"
      : >"$log_file"
      # Redirect to file (not a pipe) so deliver does not hit non-interactive prompts via tee.
      run_fastlane_cmd "$@" >>"$log_file" 2>&1
    else
      run_fastlane_cmd "$@"
    fi
  ) || status=$?

  if [[ -n "$log_file" && -f "$log_file" ]]; then
    cat "$log_file"
  fi

  if [[ "$status" -eq 0 ]]; then
    log_info "Fastlane exit 0: $*"
  else
    log_warn "Fastlane exit $status: $*"
    if [[ -n "$log_file" && -f "$log_file" ]]; then
      log_warn "Fastlane failure output (last 80 lines):"
      tail -n 80 "$log_file" >&2 || true
    fi
  fi
  return "$status"
}
