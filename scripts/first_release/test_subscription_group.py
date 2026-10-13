"""Выбор группы подписок: работаем с той, где продукты уже лежат.

Pulse 3, 12 октября: продукты были в группе «PRO», листинг называл группу
«premium» — скрипт завёл пустую «premium», а «PRO» осталась без названия для
показа, и подписки повисли в MISSING_METADATA.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from setup_app import Problem  # noqa: E402
from setup_subscriptions import pick_group  # noqa: E402

WEEK, MONTH = "week.pulse3.app", "month.pulse3.app"


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def main():
    ok = True
    pro = {"id": "22288953", "name": "PRO", "products": [WEEK, MONTH]}
    empty = {"id": "22467491", "name": "premium", "products": []}

    gid, note = pick_group([pro], "premium", [WEEK, MONTH])
    ok &= check("Pulse 3: берём «PRO», где лежат продукты", gid == "22288953")
    ok &= check("и пишем, почему не «premium»", note is not None and "«PRO»" in note and "«premium»" in note)

    gid, note = pick_group([empty, pro], "premium", [WEEK, MONTH])
    ok &= check("пустая группа с именем из листинга не перебивает настоящую", gid == "22288953")

    gid, note = pick_group([pro], "PRO", [WEEK, MONTH])
    ok &= check("имя совпало — без заметки", gid == "22288953" and note is None)

    gid, note = pick_group([pro], "premium", [WEEK, "year.pulse3.app"])
    ok &= check("часть продуктов есть — берём их группу, новый продукт заведётся там же", gid == "22288953")

    gid, note = pick_group([empty], "premium", [WEEK, MONTH])
    ok &= check("продуктов нет нигде — по имени, как раньше", gid is None and note is None)

    split = [{"id": "1", "name": "PRO", "products": [WEEK]}, {"id": "2", "name": "Premium", "products": [MONTH]}]
    try:
        pick_group(split, "premium", [WEEK, MONTH])
        ok &= check("разные группы — ошибка", False)
    except Problem as error:
        ok &= check("разные группы — понятная ошибка с обеими группами", "«PRO»" in str(error) and "«Premium»" in str(error))

    print("Итог: всё сходится" if ok else "Итог: есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
