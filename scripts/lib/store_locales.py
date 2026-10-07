"""Локали App Store и то, как люди называют папки в архивах.

Общий модуль без зависимостей: им пользуются и подготовка скриншотов
(prepare_metadata.py), и A/B-тесты (ab_test/upload.py). Раньше у A/B был свой
шаблон `xx-YY`, который принимал `en-UK` — несуществующую у Apple локаль, — и
отклонял `EN-us`. Один список на всех, чтобы правила не расходились.
"""

# Ровно то, что принимает App Store. Список снят из отказа fastlane на живом
# прогоне (FamilyTree 20, 7 октября), а не по памяти.
STORE_LOCALES = (
    "ar-SA", "bn-BD", "ca", "cs", "da", "de-DE", "el", "en-AU", "en-CA",
    "en-GB", "en-US", "es-ES", "es-MX", "fi", "fr-CA", "fr-FR", "gu-IN", "he",
    "hi", "hr", "hu", "id", "it", "ja", "kn-IN", "ko", "ml-IN", "mr-IN", "ms",
    "nl-NL", "no", "or-IN", "pa-IN", "pl", "pt-BR", "pt-PT", "ro", "ru", "sk",
    "sl-SI", "sv", "ta-IN", "te-IN", "th", "tr", "uk", "ur-PK", "vi",
    "zh-Hans", "zh-Hant",
)

# Как папки называют люди — и как это называет Apple. `en-UK` самая частая:
# в интерфейсе App Store Connect язык подписан «English (U.K.)».
FOLDER_ALIASES = {
    "en-uk": "en-GB",
    "en_gb": "en-GB",
    "en_us": "en-US",
    "uk-ua": "uk",
    "zh-cn": "zh-Hans",
    "zh-tw": "zh-Hant",
    "pt-br": "pt-BR",
}

_BY_KEY = {locale.lower(): locale for locale in STORE_LOCALES}


def store_locale(name):
    """Имя папки → локаль App Store, или None, если это не локаль."""
    key = str(name).strip().lower()
    return FOLDER_ALIASES.get(key) or _BY_KEY.get(key)
