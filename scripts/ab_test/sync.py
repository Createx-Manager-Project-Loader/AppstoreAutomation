#!/usr/bin/env python3
"""Чтение A/B-тестов приложения — для кнопки «обновить» в консоли.

Ничего не пишет. Нужен потому, что консоль сама в Apple сходить не может:
ключи лежат в репозитории приложения запечатанными, и GitHub не отдаёт их
обратно. Поэтому живое состояние приносит сюда прогон, а консоль показывает
последний привезённый слепок с отметкой времени.

Результат уезжает артефактом прогона, консоль его забирает.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

import experiments as exp  # noqa: E402
from upload_screenshots_api import (  # noqa: E402
    AppStoreConnectClient,
    find_app,
    require_env,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=Path(require_env("ASC_KEY_PATH")),
    )
    app = find_app(client, require_env("APP_IDENTIFIER"))

    try:
        items = exp.list_experiments(client, app["id"])
    except exp.Problem as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"app_id": app["id"], "experiments": items},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")

    # Тот же JSON уходит в лог между маркерами: консоль читает состояние
    # оттуда. Артефакт приезжает zip-ом, а распаковывать его в консоли нечем —
    # зависимость ради одного файла не стоит того.
    print("<<<AB-STATE")
    print(json.dumps({"experiments": items}, ensure_ascii=False))
    print("AB-STATE>>>")

    print(f"Тестов в App Store Connect: {len(items)}")
    for item in items:
        names = ", ".join(t["name"] or "?" for t in item["treatments"]) or "без вариантов"
        print(f"  — «{item['name']}» ({item['id']}), состояние {item['state']}, "
              f"трафик {item['trafficProportion']}%: {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
