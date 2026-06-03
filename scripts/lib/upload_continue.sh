# Shared helpers: continue the pipeline when an upload step partially fails.
# Source after report.sh (uses report_warning).

: "${AUTOMATION_HAD_FAILURES:=false}"

# Run a step; on non-zero exit, record a warning and keep going.
report_continue_step() {
  local label="$1"
  shift

  if "$@"; then
    return 0
  fi

  local code=$?
  AUTOMATION_HAD_FAILURES=true
  echo "WARNING: ${label} failed (exit ${code}). Continuing with remaining steps." >&2
  report_warning "${label} failed (exit ${code}); continuing with remaining steps."
  return 0
}
