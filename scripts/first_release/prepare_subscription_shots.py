#!/usr/bin/env python3
"""Готовит кадры для ревью подписок: скачать архив, снять метаданные, разложить.

От скриншотов приложения отличается раскладкой: у этих кадров нет локалей, и
папки в архиве не нужны — привязка к тарифу идёт **именем файла**, которое
должно быть ровно product id. Это же правило написано ПМу в консоли.

Очистка метаданных обязательна и здесь: кадры уезжают к ревьюеру Apple, и
оставлять в них EXIF с моделью телефона и геометкой незачем.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

from metaclean import strip_metadata  # noqa: E402
from paths import PREPARED_DIR  # noqa: E402
from prepare_metadata import download_google_drive_file  # noqa: E402

TARGET_DIR = PREPARED_DIR / "subscription-screenshots"
ARCHIVE = PREPARED_DIR / "downloaded_subscription_screenshots.zip"
IMAGES = {".png", ".jpg", ".jpeg"}


def prepare(url: str) -> Path:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for stale in TARGET_DIR.iterdir():
        stale.unlink()

    download_google_drive_file(url, ARCHIVE, "subscription screenshots ZIP")
    strip_metadata(ARCHIVE, "subscription screenshots ZIP")

    taken, skipped = 0, []
    with zipfile.ZipFile(ARCHIVE) as archive:
        for member in archive.infolist():
            name = Path(member.filename)
            # Служебное содержимое архивов с мака: __MACOSX, .DS_Store, папки.
            if member.is_dir() or name.name.startswith(".") or "__MACOSX" in member.filename:
                continue
            if name.suffix.lower() not in IMAGES:
                skipped.append(member.filename)
                continue
            # Папки игнорируем намеренно: значение несёт имя файла.
            target = TARGET_DIR / name.name
            with archive.open(member) as source:
                target.write_bytes(source.read())
            taken += 1

    if skipped:
        print(f"WARNING: не картинки в архиве подписок, пропущены: {skipped}", file=sys.stderr)
    if taken == 0:
        print("ERROR: в архиве подписок нет ни одной картинки", file=sys.stderr)
        raise SystemExit(1)

    print(f"Кадров для ревью подписок: {taken} → {TARGET_DIR}")
    for path in sorted(TARGET_DIR.iterdir()):
        print(f"  {path.stem}")
    return TARGET_DIR


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: prepare_subscription_shots.py <url архива>", file=sys.stderr)
        raise SystemExit(2)
    prepare(sys.argv[1])
