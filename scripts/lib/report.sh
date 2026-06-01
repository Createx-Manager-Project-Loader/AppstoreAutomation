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
