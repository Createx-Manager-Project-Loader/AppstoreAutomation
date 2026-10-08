"""Валюта цены выбирает базовую страну; старая форма «8.99 USD» понимается."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from currency import CurrencyError, currency_of, territory_of  # noqa: E402
from setup_subscriptions import products_from  # noqa: E402

def raises(fn):
    try:
        fn()
        return False
    except CurrencyError:
        return True

product = lambda **extra: {"subscriptions": {"products": [{
    "id": {"value": "w"}, "display_name": {"value": "W"}, "description": {"value": "D"},
    "duration": "1 week", **extra}]}}

eur, _ = products_from(product(price={"value": 8.99}, currency={"value": "EUR"}))
old, _ = products_from(product(price={"value": "8.99 USD"}))
bad, skipped = products_from(product(price={"value": 8.99}, currency={"value": "XYZ"}))

checks = [
    ("отдельное поле главнее", currency_of("8.99 USD", "EUR") == "EUR"),
    ("валюта из цены", currency_of("16.99 GBP") == "GBP"),
    ("символ €", currency_of("€4.99") == "EUR"),
    ("без валюты — доллары", currency_of(6.99) == "USD"),
    ("евро — база Германия", territory_of("EUR") == "DEU"),
    ("неизвестная валюта — ошибка", raises(lambda: currency_of(1, "XYZ"))),
    ("продукт в евро", eur[0]["currency"] == "EUR" and eur[0]["price"] == 8.99),
    ("старая форма — доллары", old[0]["currency"] == "USD"),
    ("неизвестная валюта — продукт пропущен с причиной", not bad and "XYZ" in skipped[0]),
]
ok = True
for label, cond in checks:
    ok &= cond
    print(("OK   " if cond else "ПЛОХО") + " " + label)
sys.exit(0 if ok else 1)
