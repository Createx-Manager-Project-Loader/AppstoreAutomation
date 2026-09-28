#!/usr/bin/env python3
"""Снимок карточки перед первой заливкой и защита уже заполненных полей.

Первая заливка рассчитана на приложение, которое в App Store Connect только
завели. Но между заведением и заливкой ПМ успевает что-то вбить руками, и
deliver переписал бы это молча — а вернуть было бы не из чего: истории
изменений ASC через API не отдаёт. Это не выдуманный риск: ровно так я затёр
39 локализаций на тестовом приложении и восстановил их только потому, что
успел снять снимок.

Здесь три действия, и снимок идёт первым:

1. **Снимок** — всё, что заливка может затронуть: локализации карточки и
   версии, категории, детали ревью, атрибуты версии, наличие скриншотов.
   Ложится файлом в подготовленную папку и уезжает артефактом прогона.
2. **Основной язык** — берётся из самого App Store Connect, а не из файла
   листинга. В файле стоит язык, который выбрал разработчик, и он может не
   совпасть: у приложения основным может быть en-CA, а в файле en-US. Тогда
   заливка завела бы лишнюю американскую локализацию, а основная канадская
   осталась бы пустой — и вскрылось бы это уже на ревью. Раскладка
   переносится в тот язык, который у приложения настоящий.
3. **Сверка по полям** — каждое поле, которое заливка собирается записать,
   сверяется с тем, что сейчас в сторе. Заполненное не трогаем: файл из него
   уносится, и deliver про него не узнаёт. Пропуск не молчаливый — он уходит
   в отчёт построчно.

Прогон при этом не останавливается: пустые поля заполняются, занятые
остаются. Галочка перезаписи в консоли (FIRST_RELEASE_OVERWRITE=yes) снимает
правило целиком и возвращает старое поведение «залить поверх всего».
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

# Поле в App Store Connect → файл, которым его заливает deliver.
# Имена файлов взяты из раскладки build_metadata.py: не совпадут — защита
# станет бесполезной, потому что уносить будет нечего.
VERSION_FILES = {
    "description": "description.txt",
    "keywords": "keywords.txt",
    "promotionalText": "promotional_text.txt",
    "supportUrl": "support_url.txt",
    "marketingUrl": "marketing_url.txt",
}

INFO_FILES = {
    "name": "name.txt",
    "subtitle": "subtitle.txt",
}

REVIEW_FILES = {
    "contactFirstName": "first_name.txt",
    "contactLastName": "last_name.txt",
    "contactPhone": "phone_number.txt",
    "contactEmail": "email_address.txt",
    "demoAccountName": "demo_user.txt",
    "demoAccountPassword": "demo_password.txt",
    "notes": "notes.txt",
}


def preview(value: str) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= 40 else text[:37] + "…"


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

    # Скриншоты: наборы могут существовать пустыми, поэтому считаем сами кадры,
    # а не наборы. Иначе «скриншоты уже есть» сработало бы на пустышке.
    shots: dict[str, int] = {}
    for row in snapshot["version_localizations"]:
        locale = row["attributes"].get("locale")
        try:
            payload = client.request(
                "GET", f"/appStoreVersionLocalizations/{row['id']}"
                       "/appScreenshotSets?include=appScreenshots&limit=50")
        except Exception:
            continue
        shots[locale] = sum(
            1 for item in payload.get("included", []) if item["type"] == "appScreenshots")
    snapshot["screenshot_counts"] = shots

    return snapshot


def primary_locale(snapshot: dict) -> str | None:
    return snapshot["app"]["attributes"].get("primaryLocale")


def occupied(snapshot: dict, locale: str) -> dict:
    """Что из заливаемого уже заполнено в сторе — по одному основному языку.

    Остальные языки первая заливка не трогает: в файле листинга язык один.
    """
    filled: dict = {"version": {}, "info": {}, "flat": {}, "review": {}, "screenshots": 0}

    for row in snapshot["version_localizations"]:
        if row["attributes"].get("locale") != locale:
            continue
        for field in VERSION_FILES:
            value = (row["attributes"].get(field) or "").strip()
            if value:
                filled["version"][field] = preview(value)

    for row in snapshot["info_localizations"]:
        if row["attributes"].get("locale") != locale:
            continue
        for field in INFO_FILES:
            value = (row["attributes"].get(field) or "").strip()
            if value:
                filled["info"][field] = preview(value)

    copyright_value = (snapshot["version"]["attributes"].get("copyright") or "").strip()
    if copyright_value:
        filled["flat"]["copyright.txt"] = preview(copyright_value)

    relationships = snapshot["app_info"]["data"].get("relationships", {})
    for field, name in (("primaryCategory", "primary_category.txt"),
                        ("secondaryCategory", "secondary_category.txt")):
        data = (relationships.get(field) or {}).get("data")
        if data:
            filled["flat"][name] = data.get("id", "задана")

    detail = snapshot.get("review_detail")
    if detail:
        for field in REVIEW_FILES:
            value = (detail["attributes"].get(field) or "").strip()
            if value:
                # Пароль демо-аккаунта в отчёт целиком не выводим.
                filled["review"][field] = (
                    "задан" if field == "demoAccountPassword" else preview(value))

    filled["screenshots"] = snapshot.get("screenshot_counts", {}).get(locale, 0)
    return filled


def move_locale(metadata: Path, locale: str) -> str | None:
    """Переносит раскладку в язык, который у приложения основной.

    Возвращает прежнее имя, если перенос был. Папок в раскладке ровно одна:
    листинг описывает один язык.
    """
    existing = [d for d in sorted(metadata.iterdir()) if d.is_dir()
                and d.name != "review_information"]
    if len(existing) != 1 or existing[0].name == locale:
        return None

    source = existing[0]
    target = metadata / locale
    if target.exists():
        for item in source.iterdir():
            item.replace(target / item.name)
        source.rmdir()
    else:
        source.rename(target)
    return source.name


def prune(metadata: Path, locale: str, filled: dict) -> list[str]:
    """Уносит файлы тех полей, что в сторе уже заполнены.

    deliver заливает то, что лежит на диске: нет файла — нет и записи. Это
    надёжнее, чем уговаривать deliver пропустить поле опцией.
    """
    left: list[str] = []
    locale_dir = metadata / locale

    for field, name in {**VERSION_FILES, **INFO_FILES}.items():
        if field not in {**filled["version"], **filled["info"]}:
            continue
        path = locale_dir / name
        current = filled["version"].get(field) or filled["info"].get(field)
        if path.exists():
            path.unlink()
            left.append(f"{locale}/{name}: в сторе «{current}»")

    for name, current in filled["flat"].items():
        path = metadata / name
        if path.exists():
            path.unlink()
            left.append(f"{name}: в сторе «{current}»")

    # Контакт для ревью Apple принимает только целиком, поэтому и пропускаем
    # его целиком: половина нового поверх половины старого — худший исход.
    if filled["review"]:
        review_dir = metadata / "review_information"
        removed = 0
        for name in REVIEW_FILES.values():
            path = review_dir / name
            if path.exists():
                path.unlink()
                removed += 1
        if removed:
            left.append(f"review_information: контакт для ревью уже заполнен "
                        f"({len(filled['review'])} полей)")

    return left


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="куда положить снимок")
    parser.add_argument("--metadata", type=Path,
                        help="раскладка из шага 1: перенести в основной язык и "
                             "унести уже заполненные поля")
    parser.add_argument("--plan", type=Path,
                        help="куда положить решение по скриншотам для run.sh")
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

    locale = primary_locale(snapshot)
    if not locale:
        print("ERROR: App Store Connect не отдал основной язык приложения — "
              "без него непонятно, в какую локализацию раскладывать тексты.",
              file=sys.stderr)
        return 1
    print(f"Основной язык приложения в App Store Connect: {locale}")

    overwrite = os.environ.get("FIRST_RELEASE_OVERWRITE", "").strip().lower() in (
        "yes", "true", "1")
    filled = occupied(snapshot, locale)
    plan = {"locale": locale, "skip_screenshots": False, "skip_deliver": False}

    if args.metadata and args.metadata.exists():
        moved = move_locale(args.metadata, locale)
        if moved:
            print(f"Раскладка перенесена: {moved} → {locale} "
                  "(в файле листинга был другой язык)")

    if overwrite:
        print("Галочка перезаписи выставлена — заливаем поверх всего, "
              f"прежнее содержимое остаётся только в снимке {args.out}")
    else:
        left = prune(args.metadata, locale, filled) if args.metadata else []
        if filled["screenshots"]:
            plan["skip_screenshots"] = True
            left.append(f"скриншоты: в сторе уже {filled['screenshots']} кадров")

        # Унесли всё до последнего файла — значит заливать нечем. Звать
        # deliver с пустой раскладкой незачем: он создаст версию и ничего в
        # неё не запишет, а в логе останется загадочный пустой прогон.
        if args.metadata and not any(args.metadata.rglob("*.txt")):
            plan["skip_deliver"] = True

        if left:
            print(f"\nОставлено как было: {len(left)} — в сторе уже заполнено, "
                  "из файла не перезаписывали:")
            for line in left:
                print(f"  - {line}")
            print("Чтобы залить поверх, поставьте галочку перезаписи в консоли.")
            if plan["skip_deliver"]:
                print("Заполнено всё, что было в файле — заливать нечего, "
                      "шаг deliver пропускается.")
        else:
            print("Карточка пустая — заливаем с нуля, как и задумано.")

    if args.plan:
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        args.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
