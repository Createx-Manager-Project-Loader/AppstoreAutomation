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
        ("zh-CN", "zh-Hans"), ("pt-br", "pt-BR"), ("Portuguese Brazil", "pt-BR")]
BAD = ["ENG", "xx-YY", "en_uk", "Localization 1", "screenshots", ""]


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
    for name in list(pm.STORE_LOCALES) + [n for n, _ in GOOD]:
        produced.update(pm.locales_for_folder(name))
    extra = sorted(produced - APPLE)
    ok &= check(f"ни одной локали мимо списка Apple (лишние: {extra or 'нет'})", not extra)

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
