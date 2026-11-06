#!/usr/bin/env bash
# Шаг прогона «Выпуск»: одно действие с версией в App Store по кнопке из консоли.
#   RELEASE_ACTION=settings|release|pause|resume|complete
#   RELEASE_VERSION, RELEASE_TYPE, RELEASE_DATE, PHASED_RELEASE — см. release.py
set -euo pipefail

RELEASE_SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$RELEASE_SCRIPTS/.." && pwd)"
source "$SCRIPTS_DIR/load_account_config.sh"

python3 "$RELEASE_SCRIPTS/release.py" \
  --action "${RELEASE_ACTION:?не задано действие}" \
  --version "${RELEASE_VERSION:-}" \
  --release-type "${RELEASE_TYPE:-}" \
  --release-date "${RELEASE_DATE:-}" \
  --phased "${PHASED_RELEASE:-}"
