"""Разбор цены и длительности подписки. App Store Connect не трогаем.

Проверяем на том, что реально приходило в файлах листинга: «6.99 USD» от
скилла, «$6.99» руками, «6,99» с запятой. Каждая непонятая цена — это
пропущенный продукт и пустой пейволл в сторе.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from setup_app import Problem  # noqa: E402
from setup_subscriptions import period_of, price_of, products_from  # noqa: E402

PRICES = [("6.99 USD", 6.99), ("$6.99", 6.99), ("6,99", 6.99), ("6.99", 6.99),
          (6.99, 6.99), ("USD 12.00", 12.0), ("  9.99  ", 9.99)]
BAD_PRICES = ["", "бесплатно", "USD"]
PERIODS = [("1 week", "ONE_WEEK"), ("1 Month", "ONE_MONTH"), ("3 months", "THREE_MONTHS"),
           ("1 year", "ONE_YEAR"), ("1 years", "ONE_YEAR"), ("6 months.", "SIX_MONTHS")]
BAD_PERIODS = ["weekly", "7 days", ""]


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def raises(fn, value):
    try:
        fn(value)
    except Problem:
        return True
    return False


def main():
    ok = True
    for raw, want in PRICES:
        ok &= check(f"цена {raw!r} → {want}", price_of(raw) == want)
    for raw in BAD_PRICES:
        ok &= check(f"цена {raw!r} отвергается", raises(price_of, raw))
    for raw, want in PERIODS:
        ok &= check(f"длительность {raw!r} → {want}", period_of(raw) == want)
    for raw in BAD_PERIODS:
        ok &= check(f"длительность {raw!r} отвергается", raises(period_of, raw))

    # Продукт целиком — так, как его пишет скилл.
    listing = {"subscriptions": {"products": [{
        "id": {"value": "week.famroots.com.routemaster", "status": "confirmed"},
        "duration": "1 week",
        "display_name": {"value": "Premium Weekly", "status": "confirmed"},
        "description": {"value": "Unlimited relatives", "status": "confirmed"},
        "price": {"value": "6.99 USD", "status": "confirmed"},
    }]}}
    products, skipped = products_from(listing)
    ok &= check("продукт из файла листинга собирается", len(products) == 1 and not skipped)
    if products:
        ok &= check("период и цена разобраны",
                    products[0]["period"] == "ONE_WEEK" and products[0]["price"] == 6.99)

    # Неподтверждённая цена — продукт пропускается, а не уезжает без цены.
    listing["subscriptions"]["products"][0]["price"] = {"value": "6.99", "status": "guessed"}
    products, skipped = products_from(listing)
    ok &= check("догадка по цене пропускает продукт", not products and len(skipped) == 1)

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
