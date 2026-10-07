"""Имена папок в архиве скриншотов. App Store Connect не трогаем.

Имя, похожее на локаль, но несуществующее, раньше принималось на веру: папка
раскладывалась под ним, а прогон падал позже — на заливке карточки, где
fastlane сверяет имена со своим списком, и падал целиком, вместе с
метаданными. Живой случай: FamilyTree 20, папка `en-UK`.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOMATION_CONFIG_PATH", "/dev/null")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import prepare_metadata as pm  # noqa: E402

# Имена, которые App Store принимает. Список взят из отказа fastlane на
# живом прогоне, а не придуман.
APPLE = set("""ar-SA bn-BD ca cs da de-DE el en-AU en-CA en-GB en-US es-ES es-MX fi
fr-CA fr-FR gu-IN he hi hr hu id it ja kn-IN ko ml-IN mr-IN ms nl-NL no or-IN pa-IN
pl pt-BR pt-PT ro ru sk sl-SI sv ta-IN te-IN th tr uk ur-PK vi zh-Hans zh-Hant""".split())

GOOD = [("en-UK", "en-GB"), ("EN-uk", "en-GB"), ("en-GB", "en-GB"),
        ("en-us", "en-US"), ("RU", "ru"), ("ta-IN", "ta-IN"),
        ("zh-CN", "zh-Hans"), ("pt-br", "pt-BR")]
# Только коды: названия языков словами — не локаль (решение владельца,
# единый концепт для всех заливок).
BAD = ["ENG", "xx-YY", "en_uk", "Localization 1", "screenshots", "",
       "English", "Portuguese Brazil", "Chinese simplified", "German"]


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def main():
    ok = True
    for name, want in GOOD:
        got = pm.locales_for_folder(name)
        ok &= check(f"{name:20s} → {want}", got == [want])
    for name in BAD:
        got = pm.locales_for_folder(name)
        ok &= check(f"{name!r:20s} не локаль", got == [])

    # Всё, что мы готовы отдать Apple, Apple обязана принять.
    produced = set()
    from store_locales import STORE_LOCALES
    for name in list(STORE_LOCALES) + [n for n, _ in GOOD]:
        produced.update(pm.locales_for_folder(name))
    extra = sorted(produced - APPLE)
    ok &= check(f"ни одной локали мимо списка Apple (лишние: {extra or 'нет'})", not extra)

    # Кадры в корне архива — в основной язык, но только если папок языка нет.
    import tempfile
    import zipfile as zf
    work = Path(tempfile.mkdtemp())

    def archive(name, files):
        path = work / name
        with zf.ZipFile(path, "w") as out:
            for item in files:
                out.writestr(item, b"x")
        return zf.ZipFile(path)

    def placed(archive_file):
        return sorted((locale, str(rel)) for _, locale, rel in pm.safe_zip_members(archive_file))

    root = archive("root.zip", ["01 · Resemblance.jpg", "02 · Creations.jpg",
                                "__MACOSX/._01 · Resemblance.jpg", "notes.txt"])
    os.environ.pop("SCREENSHOTS_DEFAULT_LOCALE", None)
    ok &= check("без основного языка корень не трогаем", placed(root) == [])

    os.environ["SCREENSHOTS_DEFAULT_LOCALE"] = "en-us"
    ok &= check("кадры из корня ушли в основной язык",
                placed(root) == [("en-US", "01 · Resemblance.jpg"), ("en-US", "02 · Creations.jpg")])
    ok &= check("корень больше не «непонятая папка»",
                pm.unmatched_screenshot_folders(root) == [])

    mixed = archive("mixed.zip", ["ru/1.jpg", "stray.jpg"])
    ok &= check("есть папка языка — лишний файл в корне не трогаем",
                placed(mixed) == [("ru", "1.jpg")])
    os.environ.pop("SCREENSHOTS_DEFAULT_LOCALE", None)

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
