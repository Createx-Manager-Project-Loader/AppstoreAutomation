#!/usr/bin/env bash
# Обвязка для отзывов: разложить ключ, выполнить действие, закоммитить
# reviews/reviews.json — консоль читает отзывы из этого файла.
set -euo pipefail

REVIEWS_SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$REVIEWS_SCRIPTS/.." && pwd)"
source "$SCRIPTS_DIR/lib/paths.sh"
source "$SCRIPTS_DIR/load_account_config.sh"

ACTION="${REVIEWS_ACTION:?не задано REVIEWS_ACTION}"
STATE="$REPO_ROOT/reviews/reviews.json"
log_step "Отзывы: $ACTION"

# Отправку от повторного запуска защищает консоль, а сбор — ещё и здесь:
# если два запуска всё же проскочили, второй увидит свежий сбор и выйдет.
if [[ "$ACTION" == "collect" && -f "$STATE" ]]; then
  if python3 - "$STATE" <<'PY'
import json, sys, datetime as d
s = json.load(open(sys.argv[1]))
at = s.get("collectedAt")
fresh = at and (d.datetime.now(d.timezone.utc) - d.datetime.fromisoformat(at.replace("Z", "+00:00"))).total_seconds() < 60
sys.exit(0 if fresh else 1)
PY
  then
    echo "Сбор был меньше минуты назад — повторять незачем."
    exit 0
  fi
fi

STATUS=0
case "$ACTION" in
  collect) python3 "$REVIEWS_SCRIPTS/reviews.py" collect --state "$STATE" || STATUS=$? ;;
  reply)   python3 "$REVIEWS_SCRIPTS/reviews.py" reply --state "$STATE" --plan "${REVIEWS_PLAN:?не задан план}" || STATUS=$? ;;
  more)    python3 "$REVIEWS_SCRIPTS/reviews.py" more --state "$STATE" --review "${REVIEWS_REVIEW:?не задан отзыв}" || STATUS=$? ;;
  *) echo "ERROR: неизвестное действие «$ACTION»" >&2; exit 1 ;;
esac

# Коммитим даже после частичного отказа: ушедшие ответы должны остаться
# записанными, иначе консоль предложит отправить их ещё раз.
if [[ -f "$STATE" ]]; then
  cd "$REPO_ROOT"
  git config user.name "github-actions[bot]"
  git config user.email "github-actions[bot]@users.noreply.github.com"
  git checkout -B main >/dev/null 2>&1
  git add reviews/reviews.json
  if ! git diff --cached --quiet; then
    git commit -q -m "reviews: $ACTION"
    # Пока шёл прогон, в main могли закоммитить настройки — догоняем и пушим.
    for attempt in 1 2 3; do
      if git push -q origin main; then break; fi
      git pull -q --rebase origin main || true
      sleep $((attempt * 2))
    done
    echo "reviews/reviews.json сохранён"
  fi
fi

# 2 — часть ответов не принята: файл сохранён, прогон красный, чтобы это
# было видно в истории.
exit "$STATUS"
