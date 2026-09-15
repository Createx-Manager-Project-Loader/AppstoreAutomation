#!/usr/bin/env python3
"""Превращает app_store_listing.yml в раскладку метаданных для fastlane deliver.

Файл собирает разработчик скиллом setup-store-legal, ПМ приносит его в консоль,
а сюда он приезжает как есть. Здесь из него раскладываются файлы ровно тех имён,
которые deliver читает с диска (проверено по исходнику гема, deliver/lib/deliver/
upload_metadata.rb), плюс то, что deliver принимает не файлами, а опциями —
возрастной рейтинг и признаки для отправки.

Главное правило, общее с консолью: **в стор уезжает только подтверждённое**.
Поле со статусом guessed или unanswered останавливает сборку. Смысл статусов
пропадает, если их можно молча пропустить: guessed это догадка скилла, которую
никто не сверял, а unanswered — вопрос, на который не ответили.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

# Локализуемые поля версии: имя файла в metadata/<locale>/
VERSION_FIELDS = {
    "version.description": "description",
    "version.keywords": "keywords",
    "version.promotional_text": "promotional_text",
    "version.support_url": "support_url",
    "version.marketing_url": "marketing_url",
}

# Локализуемые поля карточки приложения — лежат там же, но относятся к App Info
APP_FIELDS = {
    "app_information.name": "name",
    "app_information.subtitle": "subtitle",
}

# Нелокализуемое: один файл на всё приложение
FLAT_FIELDS = {
    "version.copyright": "copyright.txt",
    "app_information.primary_category": "primary_category.txt",
    "app_information.secondary_category": "secondary_category.txt",
}

# Информация для ревью — отдельный каталог review_information/
REVIEW_FIELDS = {
    "review_info.first_name": "first_name.txt",
    "review_info.last_name": "last_name.txt",
    "review_info.phone": "phone_number.txt",
    "review_info.email": "email_address.txt",
    "review_info.demo_user": "demo_user.txt",
    "review_info.demo_password": "demo_password.txt",
    "review_info.notes": "notes.txt",
}

# Названия категорий так, как их пишет App Store Connect → enum API.
# Список получен из /v1/appCategories, а не из памяти.
CATEGORIES = {
    "books": "BOOKS",
    "business": "BUSINESS",
    "developer tools": "DEVELOPER_TOOLS",
    "education": "EDUCATION",
    "entertainment": "ENTERTAINMENT",
    "finance": "FINANCE",
    "food & drink": "FOOD_AND_DRINK",
    "games": "GAMES",
    "graphics & design": "GRAPHICS_AND_DESIGN",
    "health & fitness": "HEALTH_AND_FITNESS",
    "lifestyle": "LIFESTYLE",
    "magazines & newspapers": "MAGAZINES_AND_NEWSPAPERS",
    "medical": "MEDICAL",
    "music": "MUSIC",
    "navigation": "NAVIGATION",
    "news": "NEWS",
    "photo & video": "PHOTO_AND_VIDEO",
    "productivity": "PRODUCTIVITY",
    "reference": "REFERENCE",
    "shopping": "SHOPPING",
    "social networking": "SOCIAL_NETWORKING",
    "sports": "SPORTS",
    "stickers": "STICKERS",
    "travel": "TRAVEL",
    "utilities": "UTILITIES",
    "weather": "WEATHER",
}

CATEGORY_FIELDS = {"app_information.primary_category", "app_information.secondary_category"}


def normalize_category(text: str) -> str:
    """«Health & Fitness» → HEALTH_AND_FITNESS. Enum пропускается как есть."""
    key = " ".join(text.split()).lower()
    if key in CATEGORIES:
        return CATEGORIES[key]
    upper = text.strip().upper().replace(" ", "_")
    if upper in CATEGORIES.values():
        return upper
    raise Problem(
        f"категория «{text}» не совпала ни с одной из {len(CATEGORIES)} категорий App Store"
    )


# Необязательные поля: их отсутствие не останавливает сборку.
# Всё остальное обязано быть подтверждено.
OPTIONAL = {
    "app_information.secondary_category",
    "version.promotional_text",
    "version.marketing_url",
    "review_info.demo_user",
    "review_info.demo_password",
}


class Problem(Exception):
    pass


def dig(root, path):
    node = root
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def value_of(root, path):
    """Значение поля, если оно подтверждено. Иначе объясняет, почему нет."""
    node = dig(root, path)
    if node is None:
        return None, "нет в файле"

    if isinstance(node, dict) and "value" in node:
        status = str(node.get("status") or "")
        raw = node.get("value")
        if status in ("guessed", "unanswered"):
            return None, f"статус {status}"
        if raw is None or str(raw).strip() == "":
            return None, "пустое значение"
        return str(raw), None

    if str(node).strip() == "":
        return None, "пустое значение"
    return str(node), None


def valid_phone(text: str) -> bool:
    """«+» с кодом страны и 7–15 цифр. Пробелы и дефисы Apple допускает."""
    digits = re.sub(r"\D", "", text)
    return text.strip().startswith("+") and 7 <= len(digits) <= 15


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


def build(listing: dict, out_dir: Path) -> dict:
    locale = str(dig(listing, "meta.locale") or "en-US")
    metadata = out_dir / "metadata"
    locale_dir = metadata / locale

    problems, written = [], []

    def take(path):
        text, why = value_of(listing, path)
        if text is None and path not in OPTIONAL:
            problems.append(f"{path}: {why}")
        return text

    for path, name in {**VERSION_FIELDS, **APP_FIELDS}.items():
        text = take(path)
        if text is not None:
            write(locale_dir / f"{name}.txt", text)
            written.append(f"{locale}/{name}.txt")

    for path, name in FLAT_FIELDS.items():
        text = take(path)
        if text is None:
            continue
        if path in CATEGORY_FIELDS:
            # В файле категория написана словами App Store Connect, а deliver
            # на такое пишет «Category 'Navigation' has been deprecated» и
            # просит enum. Переводим здесь, чтобы в листинге у ПМа оставались
            # читаемые названия.
            try:
                text = normalize_category(text)
            except Problem as error:
                problems.append(f"{path}: {error}")
                continue
        write(metadata / name, text)
        written.append(name)

    for path, name in REVIEW_FIELDS.items():
        text = take(path)
        if text is None:
            continue
        if path == "review_info.phone" and not valid_phone(text):
            # Apple проверяет номер и отвечает «must be in a valid format»
            # уже посреди заливки. Ловим раньше, чтобы не ронять прогон
            # на середине карточки.
            problems.append(
                f"{path}: «{text}» — нужен международный формат с кодом страны, "
                "например +44 844 209 0611")
            continue
        write(metadata / "review_information" / name, text)
        written.append(f"review_information/{name}")

    # Возрастной рейтинг здесь не раскладывается: его пишет setup_app.py прямым
    # вызовом ageRatingDeclaration. У поля должен быть ровно один владелец —
    # иначе два места пишут в одну анкету и расходятся.

    options = {}
    for key, path in [("release_type", "version.release_type"),
                      ("version_string", "version.version_string")]:
        text = take(path)
        if text is not None:
            options[key] = text

    if problems:
        raise Problem(problems)

    write_json(out_dir / "deliver_options.json", options)
    return {"locale": locale, "written": written, "options": options}


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("listing", type=Path, help="путь к app_store_listing.yml")
    parser.add_argument("--out", type=Path, required=True, help="куда разложить metadata/")
    args = parser.parse_args()

    try:
        listing = yaml.safe_load(args.listing.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"ERROR: не удалось прочитать {args.listing}: {error}", file=sys.stderr)
        return 1

    if not isinstance(listing, dict):
        print(f"ERROR: {args.listing} — не похоже на листинг App Store", file=sys.stderr)
        return 1

    try:
        result = build(listing, args.out)
    except Problem as error:
        print("ERROR: листинг не готов к заливке, незакрытые поля:", file=sys.stderr)
        for line in error.args[0]:
            print(f"  - {line}", file=sys.stderr)
        print("Чинится в файле у разработчика: в стор уезжает только подтверждённое.", file=sys.stderr)
        return 1

    print(f"Locale: {result['locale']}; files: {len(result['written'])}")
    for name in result["written"]:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
