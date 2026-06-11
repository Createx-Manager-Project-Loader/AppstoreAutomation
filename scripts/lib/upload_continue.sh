# Shared helpers: continue the pipeline when an upload step partially fails.
# Source after report.sh (uses report_warning).

: "${AUTOMATION_HAD_FAILURES:=false}"

# Run a step; on non-zero exit, record a warning and keep going.
report_continue_step() {
  local label="$1"
  shift

  local code=0
  log_step "$label"
  log_info "Command: $*"
  "$@" || code=$?
  log_step_done "$label" "$code"
  if [[ "$code" -eq 0 ]]; then
    return 0
  fi

  AUTOMATION_HAD_FAILURES=true
  log_warn "${label} failed (exit ${code}). Continuing with remaining steps."
  report_warning "${label} failed (exit ${code}); continuing with remaining steps."
  return 0
}
