#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from paths import METADATA_DIR, PREPARED_DIR

SOURCE_METADATA_DIR = METADATA_DIR
PREPARED_METADATA_DIR = PREPARED_DIR / "metadata"

DEFAULT_ITEMS = ["subtitle", "keywords", "release_notes"]


def has_description_metadata():
    return any(SOURCE_METADATA_DIR.glob("*/description.txt"))


def requested_items():
    explicit = os.environ.get("ASC_METADATA_ITEMS")
    if explicit:
        return [item.strip() for item in explicit.split(",") if item.strip()]

    items = list(DEFAULT_ITEMS)
    if has_description_metadata():
        items.append("description")
    if os.environ.get("INCLUDE_APP_NAME", "false") == "true":
        items.insert(0, "name")
    return items


def main():
    items = requested_items()
    allowed_files = {f"{item}.txt" for item in items}

    if PREPARED_METADATA_DIR.exists():
        shutil.rmtree(PREPARED_METADATA_DIR)
    PREPARED_METADATA_DIR.mkdir(parents=True, exist_ok=True)

    copied = 0
    locales = 0
    for locale_dir in sorted(path for path in SOURCE_METADATA_DIR.iterdir() if path.is_dir()):
        target_locale_dir = PREPARED_METADATA_DIR / locale_dir.name
        for source_file in sorted(locale_dir.iterdir()):
            if not source_file.is_file() or source_file.name not in allowed_files:
                continue
            target_locale_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_locale_dir / source_file.name)
            copied += 1
        if target_locale_dir.exists():
            locales += 1

    print("Prepared upload metadata items: " + ", ".join(items))
    print(f"Prepared {copied} metadata file(s) for {locales} locale(s) in {PREPARED_METADATA_DIR}.")

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from automation_report import merge_section

    merge_section(
        "metadata_upload",
        {
            "prepared_locales": locales,
            "prepared_files": copied,
            "items": ",".join(items),
        },
    )


if __name__ == "__main__":
    main()
