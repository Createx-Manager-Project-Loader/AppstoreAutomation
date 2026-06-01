#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/lib/paths.sh"

cd "$REPO_ROOT"

WORKFLOW_PATH=".github/workflows/app-store-automation.yml"

echo "=== Persist config from workflow_dispatch ==="
python3 "$SCRIPT_DIR/persist_workflow_config.py"
python3 "$SCRIPT_DIR/sync_workflow_defaults.py"

git config user.name "${GIT_AUTHOR_NAME:-github-actions[bot]}"
git config user.email "${GIT_AUTHOR_EMAIL:-github-actions[bot]@users.noreply.github.com}"

# Detached HEAD after actions/checkout — create a real branch tip for push.
git checkout -B main

config_changed=false
workflow_changed=false

if ! git diff --quiet -- "$CONFIG_PATH"; then
  config_changed=true
fi

if ! git diff --quiet -- "$WORKFLOW_PATH"; then
  workflow_changed=true
fi

if [[ "$config_changed" != "true" && "$workflow_changed" != "true" ]]; then
  echo "No config changes to commit (values already match automation-config.yaml on main)."
  exit 0
fi

if [[ "$workflow_changed" == "true" ]]; then
  echo "NOTE: Run workflow form defaults differ from the committed workflow file."
  echo "GITHUB_TOKEN cannot push changes to .github/workflows/ from Actions."
  echo "To update form defaults in git, run locally:"
  echo "  python3 automation/scripts/sync_workflow_defaults.py"
  git checkout -- "$WORKFLOW_PATH"
fi

if [[ "$config_changed" != "true" ]]; then
  echo "No automation-config.yaml changes to commit."
  exit 0
fi

git add "$CONFIG_PATH"
git commit -m "${PERSIST_COMMIT_MESSAGE:-chore(config): save settings from App Store workflow run}"
echo "Pushing automation-config.yaml to origin/main..."
git push origin main

echo "Done: automation-config.yaml saved on main."
