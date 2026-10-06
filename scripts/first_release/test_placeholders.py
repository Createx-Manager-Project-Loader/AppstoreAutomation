"""Заготовки вида [PRIVACY_POLICY_URL] не должны уезжать в стор.

Кит подставляет их, когда страницы политик ещё не захостили. Поле при этом
бывает помечено confirmed — текст-то написан. Без проверки квадратные скобки
уехали бы на страницу приложения, их увидел бы и ревьюер, и пользователи.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build_metadata import unresolved, value_of  # noqa: E402

GOOD = [
    "Privacy Policy: https://example.com/privacy.html",
    "Новинка [NEW] и пометка [BETA] — не заготовки",
    "Цена [1] за штуку",
    "",
]
BAD = [
    ("Privacy Policy: [PRIVACY_POLICY_URL]", ["[PRIVACY_POLICY_URL]"]),
    ("[SUPPORT_EMAIL] и [TERMS_OF_USE_URL]", ["[SUPPORT_EMAIL]", "[TERMS_OF_USE_URL]"]),
    ("[PRIVACY_POLICY_URL] дважды [PRIVACY_POLICY_URL]", ["[PRIVACY_POLICY_URL]"]),
]


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def main():
    ok = True
    for text in GOOD:
        ok &= check(f"чистый текст {text[:34]!r}", unresolved(text) == [])
    for text, want in BAD:
        ok &= check(f"заготовки в {text[:34]!r}", unresolved(text) == want)

    # Поле, помеченное confirmed, но с заготовкой внутри — не заливается.
    listing = {"version": {"description": {
        "value": "Текст.\n\nPrivacy Policy: [PRIVACY_POLICY_URL]", "status": "confirmed"}}}
    value, why = value_of(listing, "version.description")
    ok &= check("confirmed с заготовкой не заливается", value is None)
    ok &= check("причина называет саму заготовку", "[PRIVACY_POLICY_URL]" in (why or ""))

    listing["version"]["description"]["value"] = "Текст.\n\nPrivacy Policy: https://ok.com/p.html"
    value, why = value_of(listing, "version.description")
    ok &= check("тот же текст с живой ссылкой заливается", value is not None and why is None)

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
