"""Пробный период и grace period подписок (замечания Артёма, CarPlay2)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import setup_subscriptions as subs  # noqa: E402
from setup_subscriptions import (AppStoreConnectError, GRACE_PERIOD, Problem,  # noqa: E402
                                 Subscriptions, products_from, trial_of)

subs.PRICE_RETRY_PAUSE = 0


def raises(fn):
    try:
        fn()
        return False
    except Problem:
        return True


class Client:
    def __init__(self, need_territory=False, existing=(), grace=None):
        self.need_territory, self.existing, self.calls = need_territory, list(existing), []
        self.grace = grace or {"optIn": False, "sandboxOptIn": False,
                               "duration": None, "renewalType": None}

    def get_all(self, path):
        return self.existing

    def request(self, method, path, json=None):
        self.calls.append((method, path, json))
        if path.endswith("subscriptionGracePeriod"):
            return {"data": {"id": "g1", "attributes": self.grace}}
        if method == "POST" and self.need_territory and "territory" not in json["data"]["relationships"]:
            raise AppStoreConnectError("POST failed with 409: territory is required")
        return {}


def setup(client):
    s = Subscriptions.__new__(Subscriptions)
    s.client, s.app_id = client, "app"
    return s


one = Client()
per = Client(need_territory=True)
done = Client(existing=[{"id": "x"}])
on = Client(grace=dict(GRACE_PERIOD))
off = Client()

item = lambda offer: {"subscriptions": {"products": [{
    "id": {"value": "w"}, "display_name": {"value": "W"}, "description": {"value": "D"},
    "price": {"value": 8.99}, "duration": "1 week",
    "introductory_offer": {"value": offer, "status": "confirmed"}}]}}
paid, _ = products_from(item("$0.99 for the first month"))

checks = [
    ("«3 days free» → THREE_DAYS", trial_of("3 days free") == "THREE_DAYS"),
    ("«1 week free trial» → ONE_WEEK", trial_of("1 week free trial") == "ONE_WEEK"),
    ("P3D из .storekit", trial_of("P3D") == "THREE_DAYS"),
    ("пусто — пробного нет", trial_of(None) is None and trial_of("") is None),
    ("платное предложение — не автоматом", raises(lambda: trial_of("$0.99 for the first month"))),
    ("продукт с платным предложением всё равно заводится", paid and paid[0]["trial"] is None and paid[0]["trial_note"]),
    ("один вызов на все страны", setup(one).trial("s", "THREE_DAYS", ["USA", "DEU"]) == "заведён на все страны"
        and one.calls[0][2]["data"]["attributes"]["offerMode"] == "FREE_TRIAL"),
    ("Apple требует страну — по каждой", setup(per).trial("s", "THREE_DAYS", ["USA", "DEU"]) == "заведён в 2 странах"),
    ("уже есть — не трогаем", setup(done).trial("s", "THREE_DAYS", ["USA"]).startswith("уже есть") and not done.calls),
    ("grace уже включён — без PATCH", setup(on).grace_period() == "уже включён" and len(on.calls) == 1),
    ("grace выключен — PATCH со значениями команды", setup(off).grace_period().startswith("включён")
        and off.calls[-1][2]["data"]["attributes"] == GRACE_PERIOD),
]
ok = True
for label, cond in checks:
    ok &= bool(cond)
    print(("OK   " if cond else "ПЛОХО") + " " + label)
sys.exit(0 if ok else 1)
