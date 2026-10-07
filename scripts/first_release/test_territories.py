"""Коды стран из листинга. App Store Connect не трогаем.

`value_of` отдаёт значение строкой, поэтому список YAML доезжает сюда как
«['TUR']». Locator 73 на этом упал с «неизвестные коды стран», хотя в файле
было написано правильно.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from setup_app import Setup  # noqa: E402
from upload_screenshots_api import AppStoreConnectError  # noqa: E402


class FakeClient:
    """Отдаёт две территории — столько же, сколько «весь мир» в тесте."""

    def get_all(self, path, **kwargs):
        return [{"id": "USA"}, {"id": "DEU"}]


CASES = [
    ("['TUR']", ["TUR"]),             # так приходит список YAML через value_of
    ("[TUR]", ["TUR"]),
    ("['TUR', 'deu']", ["TUR", "DEU"]),
    ('["TUR","DEU"]', ["TUR", "DEU"]),
    ("TUR", ["TUR"]),
    ("TUR, DEU", ["TUR", "DEU"]),
    ("TUR DEU", ["TUR", "DEU"]),
    (["TUR", "deu"], ["TUR", "DEU"]),
    ("  tur  ", ["TUR"]),
]


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def main():
    setup = Setup.__new__(Setup)
    setup.client = FakeClient()
    ok = True

    for raw, want in CASES:
        got = setup.wanted_territories(raw)
        ok &= check(f"{str(raw):16s} → {want}", got == want)

    # Новое приложение: доступности нет, чтение отвечает 404. Это «пусто»,
    # и запись должна пойти в ветку создания, а не упасть на чтении.
    class Fresh(FakeClient):
        def __init__(self):
            self.calls = []

        def request(self, method, path, json=None):
            self.calls.append(method)
            if method == "GET" and "territoryAvailabilities" in path:
                raise AppStoreConnectError(f"GET {path} failed with 404: no appAvailabilities")
            return {"data": {}}

    fresh = Setup.__new__(Setup)
    fresh.client = Fresh()
    fresh.app_id = "1"
    ok &= check("404 на чтении доступности — это пусто", fresh.territory_rows() == {})
    fresh.set_countries("worldwide")
    ok &= check("у нового приложения доступность создаётся POST", "POST" in fresh.client.calls)

    for raw in ("worldwide", "Worldwide", " WORLDWIDE "):
        got = setup.wanted_territories(raw)
        ok &= check(f"{raw!r} → весь список территорий", got == ["USA", "DEU"])

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
