#!/usr/bin/env python3
"""Снимок карточки перед первой заливкой и остановка, если она не пустая.

Первая заливка рассчитана на приложение, которое в App Store Connect только
завели. Если её запустить на карточке, где уже что-то есть, deliver перепишет
тексты молча — и вернуть их будет не из чего: истории изменений ASC через API
не отдаёт. Это не выдуманный риск: ровно так я затёр 39 локализаций на
тестовом приложении и восстановил их только потому, что успел снять снимок.

Поэтому здесь два действия, и снимок идёт первым:

1. **Снимок** — всё, что заливка может затронуть: локализации карточки и
   версии, категории, детали ревью, атрибуты версии. Ложится файлом в
   подготовленную папку и уезжает артефактом прогона.
2. **Проверка** — если в карточке уже есть содержимое, прогон
   останавливается и показывает, что именно затрётся. Продолжить можно,
   выставив FIRST_RELEASE_OVERWRITE=yes: осознанное решение, а не молчание.

«Не пустая» считается по содержимому, а не по факту существования записей:
у только что заведённого приложения локализации уже есть, и имя в них
проставлено обязательным полем. Смотрим на описание, ключевые слова и
подзаголовок — их пустота и означает, что карточку ещё не заполняли.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

from setup_app import Setup  # noqa: E402
from upload_screenshots_api import (  # noqa: E402
    AppStoreConnectClient,
    find_app,
    require_env,
)

# Поля, по которым судим, заполняли карточку или нет.
VERSION_MARKERS = ("description", "keywords", "promotionalText", "marketingUrl", "supportUrl")
INFO_MARKERS = ("subtitle",)


def collect(client: AppStoreConnectClient, app_id: str) -> dict:
    setup = Setup(client, app_id, {})
    info_id = setup.app_info_id()
    version_id = setup.version_id()

    snapshot: dict = {"app_id": app_id, "app_info_id": info_id, "version_id": version_id}

    snapshot["app"] = client.request(
        "GET", f"/apps/{app_id}?fields[apps]=name,bundleId,primaryLocale,"
               "contentRightsDeclaration")["data"]

    # Категории обязательно со связями: без include ASC отдаёт только ссылки,
    # и в снимке остаётся пустота — на этом я уже обжёгся.
    snapshot["app_info"] = client.request(
        "GET", f"/appInfos/{info_id}?include=primaryCategory,secondaryCategory")

    snapshot["age_rating"] = client.request(
        "GET", f"/appInfos/{info_id}/ageRatingDeclaration")["data"]

    snapshot["info_localizations"] = client.get_all(
        f"/appInfos/{info_id}/appInfoLocalizations?limit=200")

    snapshot["version"] = client.request(
        "GET", f"/appStoreVersions/{version_id}?fields[appStoreVersions]="
               "versionString,copyright,releaseType,usesIdfa,appStoreState")["data"]

    snapshot["version_localizations"] = client.get_all(
        f"/appStoreVersions/{version_id}/appStoreVersionLocalizations?limit=200")

    try:
        snapshot["review_detail"] = client.request(
            "GET", f"/appStoreVersions/{version_id}/appStoreReviewDetail")["data"]
    except Exception:
        snapshot["review_detail"] = None

    return snapshot


def occupied(snapshot: dict) -> list[str]:
    """Что в карточке уже заполнено. Пустой список = заливать безопасно."""
    filled = []

    for row in snapshot["version_localizations"]:
        locale = row["attributes"].get("locale")
        for field in VERSION_MARKERS:
            value = (row["attributes"].get(field) or "").strip()
            if value:
                filled.append(f"{locale}: {field} ({len(value)} симв.)")

    for row in snapshot["info_localizations"]:
        locale = row["attributes"].get("locale")
        for field in INFO_MARKERS:
            value = (row["attributes"].get(field) or "").strip()
            if value:
                filled.append(f"{locale}: {field} «{value[:40]}»")

    return filled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="куда положить снимок")
    args = parser.parse_args()

    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=Path(require_env("ASC_KEY_PATH")),
    )
    app = find_app(client, require_env("APP_IDENTIFIER"))

    snapshot = collect(client, app["id"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Снимок карточки сохранён: {args.out}")
    print(f"  локализаций карточки: {len(snapshot['info_localizations'])}, "
          f"версии: {len(snapshot['version_localizations'])}")

    filled = occupied(snapshot)
    if not filled:
        print("Карточка пустая — заливаем с нуля, как и задумано.")
        return 0

    override = os.environ.get("FIRST_RELEASE_OVERWRITE", "").strip().lower() in ("yes", "true", "1")
    locales = len({line.split(":")[0] for line in filled})

    print(f"ВНИМАНИЕ: карточка уже заполнена — {len(filled)} полей в {locales} локалях.",
          file=sys.stderr)
    for line in filled[:12]:
        print(f"  - {line}", file=sys.stderr)
    if len(filled) > 12:
        print(f"  … и ещё {len(filled) - 12}", file=sys.stderr)

    if override:
        print("FIRST_RELEASE_OVERWRITE=yes — продолжаем, старое содержимое остаётся "
              f"только в снимке {args.out}", file=sys.stderr)
        return 0

    print(
        "\nПрогон остановлен. Первая заливка перепишет это целиком, а вернуть будет "
        "не из чего: истории изменений у App Store Connect нет.\n"
        "Если перезапись нужна — поставьте галочку «перезаписать заполненную карточку» "
        "в консоли и запустите ещё раз. Снимок уже снят и уедет артефактом прогона.",
        file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
