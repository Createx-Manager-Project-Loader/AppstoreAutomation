#!/usr/bin/env bash
# Обвязка для статуса в App Store: разложить ключ, прочитать статус версии,
# закоммитить store/status.json — консоль читает статус из этого файла.
set -euo pipefail

STATUS_SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$STATUS_SCRIPTS/.." && pwd)"
source "$SCRIPTS_DIR/lib/paths.sh"
source "$SCRIPTS_DIR/load_account_config.sh"

STATE="$REPO_ROOT/store/status.json"
log_step "Статус в App Store"

python3 "$STATUS_SCRIPTS/status.py" --state "$STATE"

cd "$REPO_ROOT"
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git checkout -B main >/dev/null 2>&1
git add store/status.json
# Коммитим каждый раз, даже без смены статуса: в файле время проверки, и
# консоль по пушу видит, что проверка прошла.
if ! git diff --cached --quiet; then
  git commit -q -m "store: status"
  # Пока шёл прогон, в main могли закоммитить настройки — догоняем и пушим.
  for attempt in 1 2 3; do
    if git push -q origin main; then break; fi
    git pull -q --rebase origin main || true
    sleep $((attempt * 2))
  done
  echo "store/status.json сохранён"
fi
