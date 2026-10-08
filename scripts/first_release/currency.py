"""Валюта цены → базовая страна, в которой Apple ищет ценовую точку.

Apple задаёт цену не числом с валютой, а ценовой точкой одной страны —
базовой; в остальные страны она пересчитывается сама (equalizations). До
8 октября 2026 базовой всегда была США: «8.99 EUR» искалось как 8.99 доллара,
и валюта из листинга просто терялась. Теперь валюта выбирает базовую страну.

Список — валюты, в которых команда реально ставит цены. Для евро база —
Германия: любая страна еврозоны годится, нужна одна и та же каждый раз.
Тот же список у консоли (lib/listing-edit.ts, CURRENCIES).
"""

import re

CURRENCY_TERRITORY = {
    "USD": "USA",
    "EUR": "DEU",
    "GBP": "GBR",
    "JPY": "JPN",
    "CAD": "CAN",
    "AUD": "AUS",
    "CHF": "CHE",
    "CNY": "CHN",
    "KRW": "KOR",
    "INR": "IND",
    "BRL": "BRA",
    "MXN": "MEX",
    "TRY": "TUR",
    "PLN": "POL",
    "SEK": "SWE",
    "NOK": "NOR",
    "DKK": "DNK",
}

SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}


class CurrencyError(Exception):
    pass


def currency_of(price_text, explicit=None) -> str:
    """Код валюты: из отдельного поля, иначе из самой цены, иначе USD.

    Отдельное поле главнее: его выбирает ПМ в консоли. Валюта внутри цены
    («8.99 USD») — старая форма скилла, её тоже понимаем.
    """
    if explicit is not None and str(explicit).strip():
        code = str(explicit).strip().upper()
    else:
        text = str(price_text or "")
        letters = re.findall(r"[A-Za-z]{3}", text)
        symbol = next((SYMBOLS[s] for s in SYMBOLS if s in text), None)
        code = letters[0].upper() if letters else (symbol or "USD")
        if code == "FRE":  # «free» — не валюта
            code = "USD"
    if code not in CURRENCY_TERRITORY:
        raise CurrencyError(
            f"валюта «{code}» не поддерживается; можно: {', '.join(CURRENCY_TERRITORY)}")
    return code


def territory_of(code: str) -> str:
    return CURRENCY_TERRITORY[code]
