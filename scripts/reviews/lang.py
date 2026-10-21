"""Язык отзыва — чтобы ответить на нём же.

Apple языка отзыва не отдаёт, только страну. Сервис перевода язык определяет,
но наружу его не сообщает. Поэтому так: письменность выдаёт язык сразу
(кириллица, иероглифы, арабская вязь), а латиницу решает страна — с поправкой
на английский: в Германии тоже пишут по-английски, и это видно по тому, что
перевод на английский почти не отличается от оригинала.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Страна App Store (ISO 3166-1 alpha-3) → основной язык. Коды — как у
# сервиса перевода.
TERRITORY_LANG = {
    "USA": "EN", "GBR": "EN", "CAN": "EN", "AUS": "EN", "NZL": "EN", "IRL": "EN",
    "SGP": "EN", "ZAF": "EN", "IND": "EN", "PHL": "EN", "NGA": "EN", "KEN": "EN",
    "DEU": "DE", "AUT": "DE", "CHE": "DE", "LIE": "DE",
    "FRA": "FR", "BEL": "FR", "LUX": "FR", "MCO": "FR",
    "ESP": "ES", "MEX": "ES-419", "ARG": "ES-419", "COL": "ES-419", "CHL": "ES-419",
    "PER": "ES-419", "VEN": "ES-419", "ECU": "ES-419", "GTM": "ES-419", "URY": "ES-419",
    "BOL": "ES-419", "PRY": "ES-419", "CRI": "ES-419", "PAN": "ES-419", "DOM": "ES-419",
    "ITA": "IT", "PRT": "PT-PT", "BRA": "PT-BR", "NLD": "NL", "POL": "PL",
    "TUR": "TR", "SWE": "SV", "DNK": "DA", "NOR": "NB", "FIN": "FI", "CZE": "CS",
    "SVK": "SK", "HUN": "HU", "ROU": "RO", "BGR": "BG", "GRC": "EL", "HRV": "HR",
    "UKR": "UK", "RUS": "RU", "KAZ": "RU", "BLR": "RU", "UZB": "RU", "KGZ": "RU",
    "JPN": "JA", "KOR": "KO", "CHN": "ZH-HANS", "TWN": "ZH-HANT", "HKG": "ZH-HANT",
    "MAC": "ZH-HANT", "SAU": "AR", "ARE": "AR", "EGY": "AR", "QAT": "AR", "KWT": "AR",
    "ISR": "HE", "THA": "TH", "VNM": "VI", "IDN": "ID", "MYS": "MS",
}

# Как язык называть в интерфейсе.
LANG_NAME = {
    "EN": "английский", "DE": "немецкий", "FR": "французский", "ES": "испанский",
    "ES-419": "испанский", "IT": "итальянский", "PT-PT": "португальский",
    "PT-BR": "португальский", "NL": "нидерландский", "PL": "польский", "TR": "турецкий",
    "SV": "шведский", "DA": "датский", "NB": "норвежский", "FI": "финский",
    "CS": "чешский", "SK": "словацкий", "HU": "венгерский", "RO": "румынский",
    "BG": "болгарский", "EL": "греческий", "HR": "хорватский", "UK": "украинский",
    "RU": "русский", "JA": "японский", "KO": "корейский", "ZH-HANS": "китайский",
    "ZH-HANT": "китайский", "AR": "арабский", "HE": "иврит", "TH": "тайский",
    "VI": "вьетнамский", "ID": "индонезийский", "MS": "малайский", "HI": "хинди",
}

SCRIPTS = [
    (re.compile(r"[぀-ヿ]"), "JA"),
    (re.compile(r"[가-힯]"), "KO"),
    (re.compile(r"[؀-ۿ]"), "AR"),
    (re.compile(r"[֐-׿]"), "HE"),
    (re.compile(r"[฀-๿]"), "TH"),
    (re.compile(r"[ऀ-ॿ]"), "HI"),
    (re.compile(r"[Ͱ-Ͽ]"), "EL"),
]
HAN = re.compile(r"[一-鿿]")
CYR = re.compile(r"[Ѐ-ӿ]")
UK_LETTERS = re.compile(r"[іїєґІЇЄҐ]")
LATIN = re.compile(r"[A-Za-z]")


def by_script(text: str, territory: str) -> str | None:
    for pattern, code in SCRIPTS:
        if pattern.search(text):
            return code
    if HAN.search(text):
        # Японский отзыв бывает из одних иероглифов («最高») — решает страна.
        if territory == "JPN":
            return "JA"
        return "ZH-HANT" if territory in ("TWN", "HKG", "MAC") else "ZH-HANS"
    if CYR.search(text):
        if UK_LETTERS.search(text) or territory == "UKR":
            return "UK"
        if territory == "BGR":
            return "BG"
        return "RU"
    return None


def guess(text: str, territory: str) -> str:
    """Язык без перевода: письменность, иначе страна."""
    return by_script(text, territory) or TERRITORY_LANG.get(territory, "EN")


def is_english(original: str, english: str) -> bool:
    """Перевод на английский почти не отличается — значит, писали по-английски."""
    a, b = original.lower().strip(), english.lower().strip()
    if not a or not LATIN.search(a):
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def name(code: str) -> str:
    return LANG_NAME.get(code.upper(), code)
