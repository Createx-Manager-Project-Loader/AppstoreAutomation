#!/usr/bin/env python3
"""Превращает app_store_listing.yml в раскладку метаданных для fastlane deliver.

Файл собирает разработчик скиллом setup-store-legal, ПМ приносит его в консоль,
а сюда он приезжает как есть. Здесь из него раскладываются файлы ровно тех имён,
которые deliver читает с диска (проверено по исходнику гема, deliver/lib/deliver/
upload_metadata.rb), плюс то, что deliver принимает не файлами, а опциями —
возрастной рейтинг и признаки для отправки.

Главное правило, общее с консолью: **в стор уезжает только подтверждённое**.
Поле со статусом guessed или unanswered не заливается — но и прогон не
останавливает: оно просто остаётся в сторе пустым, а его имя попадает в список
пропущенных. Так заливается всё, что готово, и не уезжает ни одна догадка —
раньше такое поле роняло весь прогон, и из-за одной незакрытой строки нельзя
было залить остальные тридцать.
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

# Пределы Apple в знаках. Те же числа у консоли (lib/listing-edit.ts):
# там ПМ не сохранит лишнее, а здесь не уезжает то, что пришло в файле
# длиннее. Без этой проверки одно описание на 4100 знаков роняет весь вызов
# deliver — вместе с названием и скриншотами, у которых всё в порядке.
LIMITS = {
    "app_information.name": 30,
    "app_information.subtitle": 30,
    "version.description": 4000,
    "version.keywords": 100,
    "version.promotional_text": 170,
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


class Problem(Exception):
    pass


def dig(root, path):
    node = root
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


# Заготовка вида [PRIVACY_POLICY_URL]: кит подставляет такие, когда страницы
# ещё не захостили. Подчёркивание обязательно — иначе под правило попали бы
# обычные пометки в тексте вроде «[NEW]».
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\]")


def unresolved(text):
    """Незакрытые заготовки в тексте, по порядку и без повторов."""
    seen = []
    for found in PLACEHOLDER.findall(text):
        if found not in seen:
            seen.append(found)
    return seen


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
        return _checked(str(raw))

    if str(node).strip() == "":
        return None, "пустое значение"
    return _checked(str(node))


def _checked(text):
    """Подтверждённое значение, но с заготовкой внутри, заливать нельзя.

    Живой случай (GenoMap): страницы политик ещё не захостили, кит подставил
    [PRIVACY_POLICY_URL] и [TERMS_OF_USE_URL] прямо в текст описания, а само
    описание пометил confirmed. Без этой проверки квадратные скобки уехали бы
    на страницу приложения — их увидели бы и ревьюер, и пользователи.
    """
    holes = unresolved(text)
    if holes:
        return None, f"в тексте осталась заготовка {', '.join(holes)}"
    return text, None


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

    problems, written, skipped = [], [], []

    def take(path):
        """Значение поля, если его можно заливать. Иначе None и запись в пропуски.

        Незаполненное поле и неподтверждённое — разные вещи, но исход у них
        один: наверх не уезжает ничего. Пустое заливать нечем, а догадку
        заливать нельзя. Поэтому прогон не встаёт, а просто оставляет поле
        пустым в сторе и называет его в конце — дозаполнить можно позже,
        руками или следующим прогоном.
        """
        text, why = value_of(listing, path)
        if text is None:
            skipped.append(f"{path}: {why}")
            return None
        if path == "version.keywords":
            # Пробел после запятой Apple принимает, но он съедает лимит.
            text = re.sub(r"\s*,\s*", ",", text.strip())
        limit = LIMITS.get(path)
        if limit and len(text.strip()) > limit:
            skipped.append(f"{path}: длиннее {limit} знаков ({len(text.strip())}) — Apple не примет")
            return None
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
                skipped.append(f"{path}: {error}")
                continue
        write(metadata / name, text)
        written.append(name)

    # Информацию для ревью здесь НЕ раскладываем: её пишет setup_app.py
    # прямым вызовом appStoreReviewDetail. Причина та же, что у возрастного
    # рейтинга — один владелец у поля, но здесь она ещё и спасает прогон.
    #
    # Apple хранит эту информацию одной записью и на PATCH без фамилии, почты
    # или телефона отвечает «You must provide a value for contactLastName»,
    # заваливая ВЕСЬ вызов deliver — вместе с описанием, ключевыми словами и
    # скриншотами, которые к ревью отношения не имеют. А deliver лезет её
    # патчить, едва увидит в каталоге хоть один файл: на FamilyTree 20 хватило
    # одних заметок, чтобы прогон встал.
    #
    # Прямой вызов пишет то, что есть, и падает в одиночку: остальная карточка
    # уезжает, а незаполненное поле видно в отчёте.

    # Возрастной рейтинг здесь не раскладывается: его пишет setup_app.py прямым
    # вызовом ageRatingDeclaration. У поля должен быть ровно один владелец —
    # иначе два места пишут в одну анкету и расходятся.

    # Подписки здесь тоже не раскладываются: их заводит setup_subscriptions.py
    # прямыми вызовами — у deliver для продуктов ничего нет.

    options = {}
    for key, path in [("release_type", "version.release_type"),
                      ("version_string", "version.version_string")]:
        text = take(path)
        if text is not None:
            options[key] = text

    if not written:
        raise Problem(skipped)

    write_json(out_dir / "deliver_options.json", options)
    return {"locale": locale, "written": written,
            "options": options, "skipped": skipped}


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
        print("ERROR: заливать нечего — ни одно поле листинга не закрыто:", file=sys.stderr)
        for line in error.args[0]:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(f"Локаль: {result['locale']}; файлов: {len(result['written'])}")
    for name in result["written"]:
        print(f"  {name}")

    if result["skipped"]:
        # Не ошибка, но и не мелочь: в сторе эти поля останутся пустыми.
        print(f"\nПропущено полей: {len(result['skipped'])} — "
              "в стор они не уедут и останутся пустыми:")
        for line in result["skipped"]:
            print(f"  - {line}")
        print("Пустое поле дозаполняется позже: правкой в файле и повторным "
              "прогоном либо руками в App Store Connect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
