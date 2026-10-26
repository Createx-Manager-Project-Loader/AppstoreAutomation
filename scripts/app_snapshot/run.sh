#!/usr/bin/env bash
# Шаг прогона «Данные из App Store Connect»: собрать один раздел снимка или
# (save) закоммитить store/snapshot.json — консоль читает снимок из него.
#   run.sh status | ab | reviews | subscriptions | languages | info | save
set -euo pipefail

SNAPSHOT_SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$SNAPSHOT_SCRIPTS/.." && pwd)"
source "$SCRIPTS_DIR/lib/paths.sh"

SECTION="${1:?не задан раздел}"
STATE="$REPO_ROOT/store/snapshot.json"

if [[ "$SECTION" == "save" ]]; then
  cd "$REPO_ROOT"
  [[ -f "$STATE" ]] || { echo "Снимка нет — сохранять нечего"; exit 0; }
  git config user.name "github-actions[bot]"
  git config user.email "github-actions[bot]@users.noreply.github.com"
  git checkout -B main >/dev/null 2>&1
  git add store/snapshot.json
  if ! git diff --cached --quiet; then
    git commit -q -m "store: snapshot"
    # Пока шёл прогон, в main могли закоммитить настройки — догоняем и пушим.
    for attempt in 1 2 3; do
      if git push -q origin main; then break; fi
      git pull -q --rebase origin main || true
      sleep $((attempt * 2))
    done
    echo "store/snapshot.json сохранён"
  fi
  exit 0
fi

source "$SCRIPTS_DIR/load_account_config.sh"
python3 "$SNAPSHOT_SCRIPTS/snapshot.py" --state "$STATE" --only "$SECTION"
