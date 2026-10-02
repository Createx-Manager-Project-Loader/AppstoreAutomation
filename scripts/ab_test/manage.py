#!/usr/bin/env python3
"""Действия над A/B-тестом: остановить, удалить, применить вариант.

Каждое действие сначала перечитывает состояние из App Store Connect и только
потом пишет. Консоль показывает слепок, которому может быть полчаса, а эти
действия необратимы или почти необратимы — решать по устаревшим данным нельзя.

Что Apple разрешает:

* **удалить** — только тест, который ещё не запускали; запущенный остаётся в
  истории вместе со статистикой, его можно лишь остановить;
* **применить вариант** — в любой момент, но действие необратимо, применяется
  один вариант на тест, и идущий тест при этом останавливается автоматически;
* **кадры и превью** варианта переезжают на основную страницу, **иконка нет**:
  её ставят иконкой по умолчанию в следующей версии приложения.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

import experiments as exp  # noqa: E402
from upload_screenshots_api import (  # noqa: E402
    AppStoreConnectClient,
    AppStoreConnectError,
    find_app,
    require_env,
)


def apply_treatment(client: AppStoreConnectClient, version_id: str,
                    treatment_id: str) -> None:
    client.request(
        "POST", "/appStoreVersionPromotions",
        json={"data": {
            "type": "appStoreVersionPromotions",
            "relationships": {
                "appStoreVersion": {
                    "data": {"type": "appStoreVersions", "id": version_id}},
                "appStoreVersionExperimentTreatment": {
                    "data": {"type": "appStoreVersionExperimentTreatments",
                             "id": treatment_id}},
            },
        }})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",
                        choices=["stop", "start", "delete", "apply", "edit"])
    parser.add_argument("--experiment", required=True, help="идентификатор теста")
    parser.add_argument("--treatment", help="идентификатор варианта, для apply")
    parser.add_argument("--name", help="новое имя теста, для edit")
    parser.add_argument("--traffic", type=int, help="доля трафика, для edit")
    args = parser.parse_args()

    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=Path(require_env("ASC_KEY_PATH")),
    )
    app = find_app(client, require_env("APP_IDENTIFIER"))

    try:
        version_id = exp.live_version_id(client, app["id"])
        existing = exp.list_experiments(client, app["id"])
    except exp.Problem as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    found = next((e for e in existing if e["id"] == args.experiment), None)
    if not found:
        print(f"ERROR: теста {args.experiment} в App Store Connect нет — "
              "его удалили или он относится к другому приложению.", file=sys.stderr)
        return 1

    print(f"Тест «{found['name']}», состояние {found['state']}")

    try:
        if args.action == "edit":
            exp.edit_experiment(client, found["id"], args.name, args.traffic)
            print("Изменено.")

        elif args.action in ("stop", "start"):
            exp.set_started(client, found["id"], args.action == "start")
            print("Остановлен." if args.action == "stop" else "Запущен.")

        elif args.action == "delete":
            exp.delete_experiment(client, found["id"], found["state"])
            print("Удалён.")

        elif args.action == "apply":
            if not args.treatment:
                print("ERROR: не указан вариант", file=sys.stderr)
                return 1
            treatment = next((t for t in found["treatments"]
                              if t["id"] == args.treatment), None)
            if not treatment:
                print(f"ERROR: варианта {args.treatment} в этом тесте нет",
                      file=sys.stderr)
                return 1
            if any(t.get("promotedDate") for t in found["treatments"]):
                print("ERROR: в этом тесте вариант уже применяли — второй "
                      "Apple применить не даст.", file=sys.stderr)
                return 1

            apply_treatment(client, version_id, treatment["id"])
            print(f"Вариант «{treatment['name']}» применён к странице приложения. "
                  "Тест при этом остановлен — так делает Apple. "
                  "Иконка не переносится: её ставят иконкой по умолчанию "
                  "в следующей версии приложения.")

    except (exp.Problem, AppStoreConnectError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
