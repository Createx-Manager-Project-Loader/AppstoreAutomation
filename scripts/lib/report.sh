#!/usr/bin/env bash

REPORT_PY="$LIB_DIR/automation_report.py"

report_init() {
  python3 "$REPORT_PY" init
}

report_merge() {
  local section="$1"
  shift
  python3 "$REPORT_PY" merge-section "$section" "$@"
}

report_warning() {
  python3 "$REPORT_PY" add warnings "$1"
}

report_error() {
  python3 "$REPORT_PY" add errors "$1"
}

report_status() {
  python3 "$REPORT_PY" set-status "$1"
}

report_print_final() {
  python3 "$REPORT_PY" print-final
}

report_locale_failure() {
  local section="$1"
  local locale="$2"
  local step="$3"
  local exit_code="$4"
  local log_file="${5:-}"
  local included_name="${6:-false}"
  local -a args=(
    record
    --section "$section"
    --locale "$locale"
    --step "$step"
    --exit-code "$exit_code"
  )

  if [[ -n "$log_file" ]]; then
    args+=(--log-file "$log_file")
  fi
  if [[ "$included_name" == "true" ]]; then
    args+=(--included-name)
  fi

  python3 "$LIB_DIR/failure_reasons.py" "${args[@]}"
}

# Set by report_continue_step (see upload_continue.sh) when a step fails but later steps should run.
: "${AUTOMATION_HAD_FAILURES:=false}"
