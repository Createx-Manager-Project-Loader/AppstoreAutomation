#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"
source "$LIB_DIR/report.sh"
source "$LIB_DIR/upload_continue.sh"

cd "$REPO_ROOT"

AUTOMATION_EXIT_CODE=0
AUTOMATION_FINISHED=false
AUTOMATION_HAD_FAILURES=false

finish_automation_run() {
  if [[ "$AUTOMATION_FINISHED" == "true" ]]; then
    return
  fi
  AUTOMATION_FINISHED=true

  if [[ "$AUTOMATION_EXIT_CODE" -eq 0 && "$AUTOMATION_HAD_FAILURES" == "true" ]]; then
    AUTOMATION_EXIT_CODE=1
  fi

  if [[ "$AUTOMATION_EXIT_CODE" -eq 0 ]]; then
    report_status success
  elif [[ "$AUTOMATION_HAD_FAILURES" == "true" ]]; then
    report_status partial
    report_error "Automation finished with one or more failed steps; successful uploads were kept."
  else
    report_status failed
    if [[ "$AUTOMATION_EXIT_CODE" -ne 0 ]]; then
      report_error "Automation stopped with exit code $AUTOMATION_EXIT_CODE."
    fi
  fi
  report_print_final || true
}

on_automation_exit() {
  local exit_code=$?
  if [[ "$exit_code" -ne 0 ]]; then
    AUTOMATION_EXIT_CODE=$exit_code
  fi
  finish_automation_run
}

trap on_automation_exit EXIT

report_init
log_step "App Store automation run"
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  log_info "GitHub Actions CI console logging enabled (workflow job output)"
fi
log_paths

eval "$(AUTOMATION_SCRIPTS_DIR="$SCRIPT_DIR" python3 - <<'PY'
import os
import sys

sys.path.insert(0, os.environ["AUTOMATION_SCRIPTS_DIR"])
from prepare_metadata import resolve_run_plan

plan = resolve_run_plan()
for key, value in plan.items():
    if isinstance(value, bool):
        print(f"{key.upper()}={'true' if value else 'false'}")
    else:
        print(f"{key.upper()}={value}")
PY
)"

source_mode_label() {
  case "$MODE" in
    screenshots) echo "screenshots and What's New" ;;
    aso) echo "ASO and What's New" ;;
    whats_new) echo "What's New only" ;;
    all) echo "all enabled steps (ASO and/or screenshots and What's New)" ;;
    *) echo "$MODE" ;;
  esac
}

echo "RUN_MODE=$MODE ($(source_mode_label))"
log_info "RUN_MODE=$MODE ($(source_mode_label))"
log_info "PREPARE_ASO=$PREPARE_ASO PREPARE_SCREENSHOTS=$PREPARE_SCREENSHOTS"
log_info "RUN_METADATA=$RUN_METADATA RUN_APP_INFO=$RUN_APP_INFO RUN_SUBSCRIPTIONS=$RUN_SUBSCRIPTIONS"
log_info "RUN_SCREENSHOTS=$RUN_SCREENSHOTS RUN_WHATS_NEW=$RUN_WHATS_NEW"

run_whats_new_only() {
  echo "Step 1/2: Preparing What's New upload..."
  bash "$SCRIPT_DIR/run_whats_new_pipeline.sh"
  echo "Step 2/2: What's New upload finished."
}

if [[ "$MODE" == "whats_new" ]]; then
  run_whats_new_only
  exit 0
fi

TOTAL_STEPS=1
[[ "$PREPARE_ASO" == "true" || "$PREPARE_SCREENSHOTS" == "true" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))
[[ "$RUN_METADATA" == "true" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))
[[ "$RUN_APP_INFO" == "true" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))
[[ "$RUN_SUBSCRIPTIONS" == "true" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))
[[ "$RUN_SCREENSHOTS" == "true" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))
[[ "$RUN_WHATS_NEW" == "true" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))

STEP=0

run_step() {
  STEP=$((STEP + 1))
  echo "Step $STEP/$TOTAL_STEPS: $*"
}

if [[ "$PREPARE_ASO" == "true" || "$PREPARE_SCREENSHOTS" == "true" ]]; then
  run_step "Preparing metadata and screenshots..."
  report_continue_step "Metadata preparation" bash "$SCRIPT_DIR/prepare_metadata.sh"
fi

run_step "Validating inputs..."
report_continue_step "Input validation" bash "$SCRIPT_DIR/validate_metadata.sh"

if [[ "$RUN_METADATA" == "true" || "$RUN_WHATS_NEW" == "true" || "$RUN_SCREENSHOTS" == "true" || "$RUN_APP_INFO" == "true" ]]; then
  echo "Ensuring editable App Store version exists..."
  report_continue_step "Editable App Store version" bash "$SCRIPT_DIR/ensure_editable_app_store_version.sh"
fi

if [[ "$RUN_METADATA" == "true" ]]; then
  if [[ "$RUN_WHATS_NEW" == "true" ]]; then
    run_step "Uploading metadata: subtitle, keywords, description..."
  else
    run_step "Uploading metadata: subtitle, keywords, description, release notes..."
  fi
  report_continue_step "Metadata upload" env SKIP_PREPARE=true bash "$SCRIPT_DIR/upload_metadata.sh"
else
  echo "Skipping metadata upload (RUN_METADATA=false for RUN_MODE=$MODE)."
  report_merge metadata_upload skipped=true status=skipped reason=run_metadata_false
fi

if [[ "$RUN_APP_INFO" == "true" ]]; then
  run_step "Uploading app names and subtitles sequentially..."
  report_continue_step "App name / subtitle upload" env SKIP_PREPARE=true bash "$SCRIPT_DIR/upload_app_info_sequential.sh"
else
  echo "Skipping app info upload (RUN_APP_INFO=false for RUN_MODE=$MODE)."
  report_merge app_info skipped=true reason=run_app_info_false
fi

if [[ "$RUN_SUBSCRIPTIONS" == "true" ]]; then
  run_step "Uploading subscription localizations..."
  report_continue_step "Subscription localizations" env SKIP_PREPARE=true bash "$SCRIPT_DIR/upload_subscriptions.sh"
else
  echo "Skipping subscription localization upload (RUN_SUBSCRIPTIONS=false for RUN_MODE=$MODE)."
  report_merge subscriptions skipped=true reason=run_subscriptions_false
fi

if [[ "$RUN_SCREENSHOTS" == "true" ]]; then
  run_step "Uploading screenshots sequentially..."
  report_continue_step "Screenshot upload" env SKIP_PREPARE=true bash "$SCRIPT_DIR/upload_screenshots_sequential.sh"
else
  echo "Skipping screenshots upload (RUN_SCREENSHOTS=false for RUN_MODE=$MODE)."
  report_merge screenshots skipped=true reason=run_screenshots_false
fi

if [[ "$RUN_WHATS_NEW" == "true" ]]; then
  run_step "Uploading What's New..."
  report_continue_step "What's New upload" bash "$SCRIPT_DIR/run_whats_new_pipeline.sh"
else
  echo "Skipping What's New upload (RUN_WHATS_NEW=false for RUN_MODE=$MODE)."
  report_merge whats_new skipped=true reason=run_whats_new_false
fi

if [[ "$AUTOMATION_HAD_FAILURES" == "true" ]]; then
  exit 1
fi
exit 0
