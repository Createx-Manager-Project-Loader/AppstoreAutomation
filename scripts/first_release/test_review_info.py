"""Информация для ревью пишется только целиком. Apple не трогаем.

Apple хранит её одной записью: PATCH без фамилии, почты или телефона валит
весь вызов deliver вместе с описанием и ключевыми словами. А deliver патчит
запись, едва увидит в каталоге хоть один файл — поэтому одни только заметки
роняли прогон. Живой случай: FamilyTree 20, 7 октября.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import build_metadata as bm  # noqa: E402

GOOD_PHONE = "+375 29 111 22 33"


def listing(**review):
    base = {
        "meta": {"locale": "en-US"},
        "app_information": {"name": {"value": "App", "status": "confirmed"}},
        "version": {"description": {"value": "Текст", "status": "confirmed"}},
        "review_info": {
            "first_name": {"value": "Jelena", "status": "confirmed"},
            "last_name": {"value": "Živanović", "status": "confirmed"},
            "phone": {"value": GOOD_PHONE, "status": "confirmed"},
            "email": {"value": "a@b.com", "status": "confirmed"},
            "notes": {"value": "Как дойти до пейволла", "status": "confirmed"},
        },
    }
    base["review_info"].update(review)
    return base


def build(data):
    root = Path(tempfile.mkdtemp()) / "out"
    result = bm.build(data, root)
    folder = root / "metadata" / "review_information"
    files = sorted(item.name for item in folder.iterdir()) if folder.is_dir() else []
    return files, result["skipped"]


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def main():
    ok = True

    files, skipped = build(listing())
    ok &= check("полный контакт — каталог пишется",
                "notes.txt" in files and "phone_number.txt" in files)

    # Нет телефона: раньше notes.txt всё равно записывался и ронял deliver.
    files, skipped = build(listing(phone={"value": None, "status": "unanswered"}))
    ok &= check("нет телефона — каталога нет вовсе", files == [])
    ok &= check("причина названа и упоминает заметки",
                any("заметки" in line for line in skipped))
    ok &= check("причина называет недостающее поле",
                any("phone" in line for line in skipped))

    # Телефон есть, но в неверном формате — Apple такой тоже не примет.
    files, skipped = build(listing(phone={"value": "8 029 111 22 33", "status": "confirmed"}))
    ok &= check("кривой телефон — каталога нет вовсе", files == [])
    ok &= check("причина про формат номера",
                any("международном формате" in line or "международн" in line
                    for line in skipped))

    # Описание при этом должно залиться: оно к ревью отношения не имеет.
    root = Path(tempfile.mkdtemp()) / "out"
    result = bm.build(listing(phone={"value": None, "status": "unanswered"}), root)
    ok &= check("описание разложено, несмотря на пропуск блока ревью",
                any("description.txt" in name for name in result["written"]))

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
