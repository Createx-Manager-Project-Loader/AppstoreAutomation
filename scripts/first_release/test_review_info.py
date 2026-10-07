"""Информация для ревью: пишем то, что есть. App Store Connect не трогаем.

Раньше её раскладывал deliver, и неполный контакт валил ВЕСЬ вызов — вместе
с описанием, ключевыми словами и скриншотами. Теперь её пишет прямой вызов
appStoreReviewDetail: заполненное уезжает, незаполненное остаётся пустым, а
отказ Apple роняет только этот шаг.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from setup_app import Setup  # noqa: E402
from upload_screenshots_api import AppStoreConnectError  # noqa: E402


class FakeClient:
    """Запоминает вызовы. `detail` — есть ли уже запись у версии."""

    def __init__(self, detail=None):
        self.detail = detail
        self.calls = []

    def request(self, method, path, json=None):
        self.calls.append((method, path, json))
        if method == "GET" and path.endswith("/appStoreReviewDetail"):
            if self.detail is None:
                raise AppStoreConnectError(f"GET {path} failed with 404: not found")
            return {"data": {"id": "d1", "attributes": self.detail}}
        return {"data": {"id": "d1", "attributes": json["data"]["attributes"]}}


def setup_with(review, detail=None):
    setup = Setup.__new__(Setup)
    setup.client = FakeClient(detail)
    setup.listing = {"review_info": review}
    setup.skipped = []
    setup._version_id = "v1"
    return setup


def field(value, status="confirmed"):
    return {"value": value, "status": status}


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def main():
    ok = True

    # Полный контакт.
    full = setup_with({
        "first_name": field("Jelena"), "last_name": field("Živanović"),
        "phone": field("+381 11 123 45 67"), "email": field("a@b.com"),
        "notes": field("Как дойти до пейволла"),
    })
    want = full.wanted_review()
    ok &= check("полный контакт собран",
                want.get("contactFirstName") == "Jelena"
                and want.get("contactPhone") == "+381 11 123 45 67"
                and want.get("notes") == "Как дойти до пейволла")
    ok &= check("демо-аккаунт не требуется", want.get("demoAccountRequired") is False)

    # Главное: без телефона всё равно пишем то, что есть.
    partial = setup_with({
        "first_name": field("Jelena"), "last_name": field("Živanović"),
        "phone": {"value": None, "status": "unanswered"}, "email": field("a@b.com"),
        "notes": field("Заметки"),
    })
    want = partial.wanted_review()
    ok &= check("без телефона блок НЕ пустеет", bool(want))
    ok &= check("уходит то, что заполнено",
                set(want) == {"contactFirstName", "contactLastName", "contactEmail",
                              "notes", "demoAccountRequired"})
    ok &= check("телефона в запросе нет", "contactPhone" not in want)

    # Пустой блок — шага не будет.
    empty = setup_with({"first_name": {"value": None, "status": "unanswered"}})
    ok &= check("совсем пусто — нечего писать", empty.wanted_review() == {})

    # Записи ещё нет: 404 на чтении и POST на запись.
    fresh = setup_with({"first_name": field("A"), "last_name": field("B")})
    ok &= check("чтения нет — проба не падает", fresh.filled_review() is None)
    fresh.set_review(fresh.wanted_review())
    methods = [c[0] for c in fresh.client.calls]
    ok &= check("создаём через POST", "POST" in methods and "PATCH" not in methods)

    # Запись есть: PATCH, и проба видит заполненное.
    existing = setup_with({"first_name": field("A")},
                          detail={"contactFirstName": "Старое", "notes": None})
    ok &= check("проба видит заполненное", existing.filled_review() == "1 полей")
    existing.set_review(existing.wanted_review())
    ok &= check("обновляем через PATCH",
                any(c[0] == "PATCH" for c in existing.client.calls))

    # Демо-аккаунт поднимает признак.
    demo = setup_with({"first_name": field("A"), "demo_user": field("tester"),
                       "demo_password": field("secret")})
    ok &= check("с демо-аккаунтом признак поднят",
                demo.wanted_review().get("demoAccountRequired") is True)

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
