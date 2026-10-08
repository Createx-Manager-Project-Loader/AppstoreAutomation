"""Цены подписки: 429 не теряет страны, а добирается медленным кругом."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import setup_subscriptions as subs  # noqa: E402
from setup_subscriptions import AppStoreConnectError, Subscriptions  # noqa: E402

subs.PRICE_RETRY_PAUSE = 0


class Client:
    def __init__(self, fail_times):
        self.fail = dict(fail_times)
        self.posted = set()

    def request(self, method, url, json=None):
        if method == "GET":
            return {"data": []}
        point = json["data"]["relationships"]["subscriptionPricePoint"]["data"]["id"]
        if self.fail.get(point, 0) > 0:
            self.fail[point] -= 1
            raise AppStoreConnectError(f"POST {url} failed with 429: RATE_LIMIT_EXCEEDED")
        self.posted.add(point)
        return {}


def run(fail):
    s = Subscriptions.__new__(Subscriptions)
    s.client = Client(fail)
    points = [f"p{i}" for i in range(10)]
    s.price_points = lambda sub_id, price: points
    subs.territory_of = lambda pid: pid
    try:
        return s.set_prices("sub", 6.99), s.client.posted
    except Exception as error:  # noqa: BLE001
        return str(error), s.client.posted


count, posted = run({"p1": 1, "p5": 2})
stuck, _ = run({"p3": 99})
checks = [
    ("после 429 все 10 цен встали", count == 10 and len(posted) == 10),
    ("вечный 429 — понятная ошибка", isinstance(stuck, str) and "1 странах" in stuck),
]
ok = True
for label, cond in checks:
    ok &= cond
    print(("OK   " if cond else "ПЛОХО") + " " + label)
sys.exit(0 if ok else 1)
