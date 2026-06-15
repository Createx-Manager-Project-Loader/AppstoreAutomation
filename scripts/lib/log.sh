#!/usr/bin/env bash

# Console logging for GitHub Actions / CI job output.
# Everything important goes to stdout/stderr so it appears in the workflow log.

: "${AUTOMATION_VERBOSE:=1}"

if [[ "${GITHUB_ACTIONS:-}" == "true" || "${CI:-}" == "true" ]]; then
  AUTOMATION_VERBOSE=1
fi

log_ts() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_info() {
  echo "[$(log_ts)] INFO  $*"
}

log_warn() {
  echo "[$(log_ts)] WARN  $*" >&2
}

log_error() {
  echo "[$(log_ts)] ERROR $*" >&2
}

log_debug() {
  if [[ "$AUTOMATION_VERBOSE" == "1" ]]; then
    echo "[$(log_ts)] DEBUG $*"
  fi
}

log_step() {
  log_info "===== $* ====="
}

log_step_done() {
  local label="$1"
  local code="${2:-0}"
  if [[ "$code" -eq 0 ]]; then
    log_info "===== $label: OK (exit 0) ====="
  else
    log_warn "===== $label: FAILED (exit $code) ====="
  fi
}

log_paths() {
  log_info "REPO_ROOT=$REPO_ROOT"
  log_info "METADATA_DIR=$METADATA_DIR"
  log_info "PREPARED_DIR=$PREPARED_DIR"
  log_info "CONFIG_PATH=$CONFIG_PATH"
  log_info "AUTOMATION_DIR=$AUTOMATION_DIR"
}

log_file_summary() {
  local file_path="$1"
  local label="${2:-file}"

  if [[ ! -f "$file_path" ]]; then
    log_info "$label missing: $file_path"
    return 0
  fi

  local size
  size="$(wc -c < "$file_path" | tr -d ' ')"
  local preview
  preview="$(LC_ALL=C head -c 200 "$file_path" | LC_ALL=C tr '\n' ' ')"
  log_info "$label $file_path (${size} bytes): ${preview}"
}

log_locale_dir_summary() {
  local locale_dir="$1"
  local locale
  locale="$(basename "$locale_dir")"

  [[ -d "$locale_dir" ]] || return 0
  log_info "Locale payload $locale:"
  for file_name in name.txt subtitle.txt keywords.txt description.txt release_notes.txt support_url.txt marketing_url.txt; do
    log_file_summary "$locale_dir/$file_name" "$locale/$file_name"
  done
}
