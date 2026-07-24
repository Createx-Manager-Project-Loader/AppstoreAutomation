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
  local use_verbose=false
  local pwd_before="$PWD"
  local -a cmd=()

  if [[ "${AUTOMATION_FASTLANE_VERBOSE:-}" == "1" ]]; then
    use_verbose=true
  fi

  log_info "Fastlane start: $*"
  log_info "APP_IDENTIFIER=${APP_IDENTIFIER:-}"
  log_info "ASC_METADATA_ITEMS=${ASC_METADATA_ITEMS:-}"
  log_info "METADATA_PATH=${METADATA_PATH:-}"

  export FASTLANE_DISABLE_COLORS=1
  export DELIVER_FORCE_OVERWRITE=1
  export FASTLANE_IS_INTERACTIVE=false
  export FASTLANE_SKIP_UPDATE_CHECK=1
  export FASTLANE_HIDE_ACTION_SUMMARY=1
  if [[ "${GITHUB_ACTIONS:-}" == "true" || "${CI:-}" == "true" ]]; then
    export CI=true
  fi

  if [[ -f "$AUTOMATION_DIR/Gemfile" ]]; then
    cmd=(bundle exec fastlane)
  else
    cmd=(fastlane)
  fi
  if [[ "$use_verbose" == "true" ]]; then
    cmd+=(--verbose)
  fi
  cmd+=("$@")

  cd "$AUTOMATION_DIR" || return 1

  if [[ -n "$log_file" ]]; then
    mkdir -p "$(dirname "$log_file")"
    : >"$log_file"
    # Redirect to file (not a pipe) so deliver does not hit non-interactive prompts via tee.
    "${cmd[@]}" >>"$log_file" 2>&1 || status=$?
  else
    "${cmd[@]}" || status=$?
  fi

  cd "$pwd_before" || true

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

# Фильтр локалей для повтора. Возвращает 0, если локаль входит в
# ASC_ONLY_LOCALES (список через запятую) либо если фильтр пуст (= все локали).
# Сравнение регистронезависимое, пробелы игнорируются — устойчиво к
# «de-DE», «de-de», « fr-FR ».
locale_selected() {
  local candidate="$1"
  local filter="${ASC_ONLY_LOCALES:-}"
  [[ -z "${filter//[[:space:]]/}" ]] && return 0

  local cand_lc
  cand_lc="$(printf '%s' "$candidate" | tr '[:upper:]' '[:lower:]')"

  local item item_lc
  IFS=',' read -ra _only <<<"$filter"
  for item in "${_only[@]}"; do
    item_lc="$(printf '%s' "${item//[[:space:]]/}" | tr '[:upper:]' '[:lower:]')"
    [[ -z "$item_lc" ]] && continue
    [[ "$cand_lc" == "$item_lc" ]] && return 0
  done
  return 1
}
