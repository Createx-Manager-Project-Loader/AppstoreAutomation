#!/usr/bin/env python3
"""Заливка кадров в варианты A/B-теста продуктовой страницы.

На вход — план из консоли, JSON:

    {
      "experiment": {"id": "", "name": "Первый кадр, октябрь", "traffic": 50},
      "treatments": [
        {"id": "", "name": "Treatment B", "zip_url": "https://drive.google.com/file/d/…"}
      ]
    }

Пустой `id` означает «завести». Непустой — «найти в сторе и обновить»; сверка
идёт по идентификатору Apple, а не по имени, чтобы переименование теста в
App Store Connect не рвало связь.

Порядок внутри жёсткий и не переставляется:

    план → сверка со стором → тест → варианты → архив → ОЧИСТКА МЕТАДАННЫХ
         → раскладка по локалям → наборы кадров → заливка → обратное чтение

Очистка обязательна, как и везде: кадры приходят с Google Drive такими, какими
их собрали руками, с EXIF внутри. Любой сбой очистки останавливает прогон — в
стор не уедет ни один кадр.

Чего здесь нет намеренно:

* **Запуска теста.** Варианты проходят ревью Apple, и старт — осознанное
  решение человека, который видел кадры. Прогон только заливает.
* **Иконок.** Их нельзя загрузить отдельно: альтернативные иконки живут в
  бинарнике приложения. Выбор иконки — отдельная задача, не эта.
* **Размеров, которых нет в архиве.** Вариант по умолчанию копия основной
  страницы: размер без своих кадров берётся с оригинала. Поэтому пустых
  наборов мы не создаём.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

import experiments as exp  # noqa: E402
from metaclean import strip_metadata  # noqa: E402
from paths import PREPARED_DIR  # noqa: E402
from prepare_metadata import download_google_drive_file  # noqa: E402
from upload_screenshots_api import (  # noqa: E402
    EXPERIMENT_PARENT,
    AppStoreConnectClient,
    AppStoreConnectError,
    display_type_for_image,
    find_app,
    image_sort_key,
    list_screenshot_sets,
    order_screenshots,
    replace_screenshot_set,
    require_env,
    upload_screenshot,
)

IMAGES = {".png", ".jpg", ".jpeg"}
LOCALE_RE = re.compile(r"^[a-z]{2}(-[A-Za-z]{2,4})?$")


def spread(archive_path: Path, label: str, target: Path) -> dict[str, list[Path]]:
    """Раскладывает кадры из архива по локалям.

    Возвращает локаль → список файлов. Папка локали берётся из пути внутри
    архива: сервис очистки структуру путей сохраняет, проверено.
    """
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    by_locale: dict[str, list[Path]] = {}
    foreign: list[str] = []

    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            name = Path(member.filename)
            if (member.is_dir() or name.name.startswith(".")
                    or "__MACOSX" in member.filename):
                continue
            if name.suffix.lower() not in IMAGES:
                foreign.append(member.filename)
                continue

            locale = next((part for part in name.parts if LOCALE_RE.match(part)), None)
            if locale is None:
                foreign.append(member.filename)
                continue

            out_dir = target / locale
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / name.name
            with archive.open(member) as source:
                out_path.write_bytes(source.read())
            by_locale.setdefault(locale, []).append(out_path)

    if foreign:
        print(f"  пропущено файлов вне папок локалей: {len(foreign)}")
    if not by_locale:
        raise exp.Problem(
            f"в архиве «{label}» нет папок по языкам. Внутри должны быть папки "
            "с кодами локалей (en-US, de-DE), а кадры — в них")

    for files in by_locale.values():
        files.sort(key=image_sort_key)
    return by_locale


def unpack(url: str, label: str, target: Path) -> dict[str, list[Path]]:
    """Скачивает архив, снимает метаданные и раскладывает его.

    Очистка стоит между скачиванием и разбором намеренно: так ни один кадр не
    попадает дальше по течению неочищенным, и обойти её нельзя, не переписав
    эти три строки.
    """
    archive_path = PREPARED_DIR / f"downloaded_{label}.zip"
    download_google_drive_file(url, archive_path, f"{label} ZIP")
    strip_metadata(archive_path, f"{label} ZIP")
    return spread(archive_path, label, target)


def fill_treatment(client: AppStoreConnectClient, treatment_id: str,
                   by_locale: dict[str, list[Path]], overwrite: bool) -> dict:
    """Заливает кадры в вариант. Возвращает, что получилось, для отчёта."""
    known = exp.treatment_localizations(client, treatment_id)
    uploaded, left, failed = 0, [], []

    for locale in sorted(by_locale):
        files = by_locale[locale]
        localization_id = exp.ensure_localization(client, treatment_id, locale, known)

        # Группируем по размеру экрана: набор кадров у Apple всегда про один
        # размер, и смешивать их в одном наборе нельзя.
        by_type: dict[str, list[Path]] = {}
        for path in files:
            by_type.setdefault(display_type_for_image(path), []).append(path)

        existing = {
            row["attributes"]["screenshotDisplayType"]
            for row in list_screenshot_sets(client, localization_id, EXPERIMENT_PARENT)
        }

        for display_type, group in sorted(by_type.items()):
            if display_type in existing and not overwrite:
                left.append(f"{locale} · {display_type}")
                continue
            try:
                set_id = replace_screenshot_set(
                    client, localization_id, display_type, False, EXPERIMENT_PARENT)
                ids = [upload_screenshot(client, set_id, path, False) for path in group]
                order_screenshots(client, set_id, ids, False)
                uploaded += len(ids)
            except (AppStoreConnectError, OSError) as error:
                failed.append(f"{locale} · {display_type}: {error}")

    return {"uploaded": uploaded, "left": left, "failed": failed}


def count_in_store(client: AppStoreConnectClient, treatment_id: str) -> int:
    """Сколько кадров реально лежит в варианте. Обратное чтение, не доверие."""
    total = 0
    for localization_id in exp.treatment_localizations(client, treatment_id).values():
        payload = client.request(
            "GET",
            f"/appStoreVersionExperimentTreatmentLocalizations/{localization_id}"
            "/appScreenshotSets?include=appScreenshots&limit=50")
        total += sum(1 for item in payload.get("included", [])
                     if item["type"] == "appScreenshots")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="план из консоли")
    parser.add_argument("--out", type=Path, help="куда положить результат для консоли")
    parser.add_argument("--overwrite", action="store_true",
                        help="заливать поверх уже заполненных размеров")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    wanted = plan.get("experiment") or {}
    treatments = plan.get("treatments") or []
    if not treatments:
        print("ERROR: в плане нет ни одного варианта", file=sys.stderr)
        return 1

    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=Path(require_env("ASC_KEY_PATH")),
    )
    app = find_app(client, require_env("APP_IDENTIFIER"))

    try:
        existing = exp.list_experiments(client, app["id"])
    except exp.Problem as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    # ── тест ───────────────────────────────────────────────────────────────
    found = next((e for e in existing if e["id"] == wanted.get("id")), None)
    if wanted.get("id") and not found:
        print(f"ERROR: теста {wanted['id']} в App Store Connect нет. "
              "Его удалили руками — заведите заново в консоли.", file=sys.stderr)
        _print_existing(existing)
        return 1

    if not found:
        name = (wanted.get("name") or "").strip()
        if not name:
            print("ERROR: не задано название теста", file=sys.stderr)
            return 1
        if any(e["name"] == name for e in existing):
            print(f"ERROR: тест с именем «{name}» в сторе уже есть, но он не наш. "
                  "Заберите его под управление консоли или дайте другое имя.",
                  file=sys.stderr)
            _print_existing(existing)
            return 1
        created = exp.create_experiment(client, app["id"], name,
                                        wanted.get("traffic") or 50)
        found = {"id": created["id"], "name": name, "treatments": [], "state": None}
        print(f"Тест заведён: «{name}» ({found['id']})")
    else:
        print(f"Тест найден: «{found['name']}» ({found['id']}), "
              f"состояние {found['state']}")

    # ── варианты ───────────────────────────────────────────────────────────
    by_id = {t["id"]: t for t in found.get("treatments", [])}
    report = {"experiment": {"id": found["id"], "name": found["name"]}, "treatments": []}

    for item in treatments:
        name = (item.get("name") or "").strip()
        treatment_id = item.get("id") or ""

        if treatment_id and treatment_id not in by_id:
            print(f"ERROR: варианта {treatment_id} в тесте нет", file=sys.stderr)
            return 1
        if not treatment_id:
            created = exp.create_treatment(client, found["id"], name)
            treatment_id = created["id"]
            print(f"  вариант заведён: «{name}» ({treatment_id})")

        entry = {"id": treatment_id, "name": name}

        if not item.get("zip_url"):
            entry["skipped"] = "архив не задан"
            report["treatments"].append(entry)
            continue

        print(f"  вариант «{name}»: готовим кадры")
        try:
            by_locale = unpack(item["zip_url"], f"ab_{treatment_id}",
                               PREPARED_DIR / "ab" / treatment_id)
        except exp.Problem as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1

        result = fill_treatment(client, treatment_id, by_locale, args.overwrite)
        entry.update(result)
        entry["in_store"] = count_in_store(client, treatment_id)
        report["treatments"].append(entry)

        print(f"    локалей в архиве: {len(by_locale)}; залито кадров: "
              f"{result['uploaded']}; в сторе сейчас: {entry['in_store']}")
        for line in result["left"]:
            print(f"    оставлено как было: {line}")
        for line in result["failed"]:
            print(f"    НЕ ЗАЛИТО: {line}", file=sys.stderr)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                            encoding="utf-8")

    failures = [line for t in report["treatments"] for line in t.get("failed", [])]
    left = [line for t in report["treatments"] for line in t.get("left", [])]
    if left:
        print(f"\nОставлено как было: {len(left)} — в сторе уже заполнено, "
              "из архива не перезаписывали. Чтобы залить поверх, поставьте "
              "галочку перезаписи в консоли.")
    if failures:
        print(f"ERROR: не залилось: {len(failures)}", file=sys.stderr)
        return 1

    print("\nКадры залиты. Тест не запущен: варианты проходят ревью Apple, "
          "и старт остаётся за человеком.")
    return 0


def _print_existing(existing: list[dict]) -> None:
    print("В App Store Connect сейчас есть:", file=sys.stderr)
    if not existing:
        print("  — ни одного теста", file=sys.stderr)
    for item in existing:
        names = ", ".join(t["name"] or "?" for t in item["treatments"]) or "без вариантов"
        print(f"  — «{item['name']}» ({item['id']}), {item['state']}: {names}",
              file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
