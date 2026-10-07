"""Проба «уже заполнено?» не должна ронять шаг на новом приложении.

У приложения, заводимого с нуля, нет ни расписания цен, ни доступности —
Apple отвечает 404 на чтение. Раньше это засчитывалось как падение шага, и
цену со странами нельзя было выставить вообще. Apple в тестах не трогаем.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from setup_app import Step, probe  # noqa: E402
from upload_screenshots_api import AppStoreConnectError  # noqa: E402

NOT_FOUND = AppStoreConnectError(
    "GET https://api.appstoreconnect.apple.com/v2/appAvailabilities/1/"
    "territoryAvailabilities failed with 404: "
    "{\"detail\": \"There is no resource of type 'appAvailabilities'\"}")
FORBIDDEN = AppStoreConnectError("GET /appPriceSchedules/1 failed with 403: no access")


def step_with(filled):
    return Step("цена", "free", lambda want: None, lambda: None, filled)


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def main():
    ok = True

    def raise_404():
        raise NOT_FOUND

    def raise_403():
        raise FORBIDDEN

    ok &= check("404 читается как «ещё не заполнено»", probe(step_with(raise_404)) is None)
    ok &= check("заполненное значение возвращается",
                probe(step_with(lambda: "free")) == "free")
    ok &= check("пустой ответ — тоже «не заполнено»",
                probe(step_with(lambda: None)) is None)

    raised = False
    try:
        probe(step_with(raise_403))
    except AppStoreConnectError:
        raised = True
    ok &= check("403 по-прежнему роняет шаг — это не «пусто»", raised)

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
