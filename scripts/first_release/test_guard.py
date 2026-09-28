"""Проверка защиты заполненных полей на подставном снимке. Apple не трогаем."""
import sys, tempfile, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard

def snapshot(**kw):
    base = {
        "app": {"attributes": {"primaryLocale": "en-CA"}},
        "app_info": {"data": {"relationships": {
            "primaryCategory": {"data": {"id": "UTILITIES"}},
            "secondaryCategory": {"data": None}}}},
        "version": {"attributes": {"copyright": "2026 Createx"}},
        "version_localizations": [{"id": "v1", "attributes": {
            "locale": "en-CA", "description": "Уже написанное описание",
            "keywords": "", "promotionalText": None,
            "supportUrl": "https://example.com", "marketingUrl": ""}}],
        "info_localizations": [{"id": "i1", "attributes": {
            "locale": "en-CA", "name": "Family Tree", "subtitle": ""}}],
        "review_detail": {"attributes": {
            "contactFirstName": "Анна", "contactLastName": "П.",
            "contactPhone": "+375291112233", "contactEmail": "a@b.by",
            "demoAccountName": "", "demoAccountPassword": "", "notes": ""}},
        "screenshot_counts": {"en-CA": 12},
    }
    base.update(kw)
    return base

def layout(locale):
    """Раскладка, как её делает build_metadata.py."""
    root = Path(tempfile.mkdtemp()) / "metadata"
    (root / locale).mkdir(parents=True)
    for name in ["description.txt", "keywords.txt", "promotional_text.txt",
                 "support_url.txt", "marketing_url.txt", "name.txt", "subtitle.txt"]:
        (root / locale / name).write_text("из файла", encoding="utf-8")
    for name in ["copyright.txt", "primary_category.txt", "secondary_category.txt"]:
        (root / name).write_text("из файла", encoding="utf-8")
    (root / "review_information").mkdir()
    for name in ["first_name.txt", "last_name.txt", "phone_number.txt", "email_address.txt"]:
        (root / "review_information" / name).write_text("из файла", encoding="utf-8")
    return root

ok = True
def check(label, got, want):
    global ok
    good = got == want
    ok &= good
    print(("  ok   " if good else "  FAIL ") + label + (f"  → {got!r}" if not good else ""))

# 1. Перенос в основной язык приложения
root = layout("en-US")
moved = guard.move_locale(root, "en-CA")
check("раскладка переехала en-US → en-CA", moved, "en-US")
check("папка en-CA появилась", (root / "en-CA").is_dir(), True)
check("папка en-US исчезла", (root / "en-US").exists(), False)
check("review_information не тронут", (root / "review_information").is_dir(), True)

# 2. Что считаем занятым
filled = guard.occupied(snapshot(), "en-CA")
check("занято в версии", sorted(filled["version"]), ["description", "supportUrl"])
check("занято в карточке", sorted(filled["info"]), ["name"])
check("занято плоских", sorted(filled["flat"]), ["copyright.txt", "primary_category.txt"])
check("контакт ревью найден", len(filled["review"]), 4)
check("скриншоты посчитаны", filled["screenshots"], 12)

# 3. Уносим занятое, оставляем свободное
left = guard.prune(root, "en-CA", filled)
loc = root / "en-CA"
check("description унесён", (loc / "description.txt").exists(), False)
check("support_url унесён", (loc / "support_url.txt").exists(), False)
check("name унесён", (loc / "name.txt").exists(), False)
check("keywords остался (в сторе пусто)", (loc / "keywords.txt").exists(), True)
check("subtitle остался", (loc / "subtitle.txt").exists(), True)
check("marketing_url остался", (loc / "marketing_url.txt").exists(), True)
check("copyright унесён", (root / "copyright.txt").exists(), False)
check("primary_category унесена", (root / "primary_category.txt").exists(), False)
check("secondary_category осталась", (root / "secondary_category.txt").exists(), True)
check("контакт ревью унесён целиком",
      any((root / "review_information").iterdir()), False)
check("строк отчёта: 3 поля + 2 плоских + контакт", len(left), 6)

# 4. Пустая карточка — не трогаем ничего
empty = snapshot(
    version={"attributes": {"copyright": None}},
    app_info={"data": {"relationships": {"primaryCategory": {"data": None},
                                         "secondaryCategory": {"data": None}}}},
    version_localizations=[{"id": "v1", "attributes": {"locale": "en-CA"}}],
    info_localizations=[{"id": "i1", "attributes": {"locale": "en-CA"}}],
    review_detail=None, screenshot_counts={})
root2 = layout("en-CA")
before = len(list(root2.rglob("*.txt")))
left2 = guard.prune(root2, "en-CA", guard.occupied(empty, "en-CA"))
check("на пустой карточке ничего не унесли", len(list(root2.rglob("*.txt"))), before)
check("отчёт пуст", left2, [])

# 5. Чужой язык в сторе не влияет на наш
other = snapshot(version_localizations=[{"id": "v2", "attributes": {
    "locale": "de-DE", "description": "Немецкое описание"}}])
check("поля чужой локали не считаются занятыми",
      guard.occupied(other, "en-CA")["version"], {})

print("ИТОГ:", "всё ок" if ok else "ЕСТЬ ОШИБКИ")
sys.exit(0 if ok else 1)
