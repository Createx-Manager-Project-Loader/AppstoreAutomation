"""Перевод для отзывов: пачками, через наш сервис перевода.

Сервис сам определяет язык текста (поле source_lang обязательно, но ни на что
не влияет — проверено 21 октября: японский с пометкой EN переводится верно).
Запросы он выполняет строго по очереди, около секунды каждый, а длинный текст
переводит почти так же быстро, как короткий. Поэтому тексты склеиваются в
пачки с разделителем и переводятся одним запросом.

В прогоне GitHub Actions сервис доступен только через консоль: прогон
предъявляет удостоверение GitHub, токен переводчика остаётся на сервере
(scripts/translate_descriptions.py). Для проверки на своей машине можно
задать TRANSLATOR_URL и TRANSLATOR_TOKEN — тогда запрос идёт напрямую.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Разделитель между текстами пачки. Число внутри — чтобы после перевода
# убедиться, что куски не перепутались и не склеились.
SEP = "\n\n⟦{n}⟧\n\n"
SEP_RE = re.compile(r"\s*⟦\s*(\d+)\s*⟧\s*")
# Пачка не длиннее: на 4 000 знаков сервис отвечает за 2 секунды, больше
# не проверяли.
BATCH_CHARS = 3500

# Английский как язык перевода — только с регионом: на «EN» сервис падает
# с 500 (проверено 21 октября). Китайский как язык перевода — ZH-HANS.
TARGET_ALIASES = {"EN": "EN-US", "ZH": "ZH-HANS", "PT": "PT-BR"}


def source_for(code: str) -> str:
    """Язык источника для запроса. Сервис определяет его сам, но если указанный
    совпал с целевым (EN → EN-US), отдаёт текст без перевода — проверено
    21 октября на немецком отзыве. Поэтому для английского указываем другой."""
    return "DE" if code.upper().startswith("EN") else "EN"


class TranslateError(RuntimeError):
    pass


def target_code(lang: str) -> str:
    code = lang.upper()
    return TARGET_ALIASES.get(code, code)


def _direct(text: str, code: str) -> str:
    url = os.environ["TRANSLATOR_URL"]
    body = json.dumps({"text": text, "source_lang": source_for(code), "dst_lang": code}).encode()
    request = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Token {os.environ['TRANSLATOR_TOKEN']}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(request, timeout=120) as response:
        return (json.loads(response.read().decode()).get("translation") or "").strip()


def _via_console(text: str, code: str) -> str:
    from translate_descriptions import translate  # noqa: WPS433 — тот же путь, что у описаний

    return translate(text, code)


def translate_one(text: str, code: str, attempts: int = 3) -> str:
    code = target_code(code)
    direct = bool(os.environ.get("TRANSLATOR_URL") and os.environ.get("TRANSLATOR_TOKEN"))
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = _direct(text, code) if direct else _via_console(text, code)
            if result:
                return result
            last = TranslateError("пустой перевод")
        except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError) as error:
            last = error
        except SystemExit as error:
            # translate_descriptions обрывает прогон, если нет DASHBOARD_URL или
            # удостоверения. Для отзывов это не повод падать: соберём без перевода.
            raise TranslateError(str(error)) from None
        if attempt < attempts:
            time.sleep(2 * attempt)
    raise TranslateError(str(last))


def _split(translated: str, count: int) -> list[str] | None:
    parts = SEP_RE.split(translated)
    # split с группой даёт: [до первого, n1, кусок1, n2, кусок2, …]
    if len(parts) != 2 * count + 1 or parts[0].strip():
        return None
    out: dict[int, str] = {}
    for i in range(1, len(parts), 2):
        out[int(parts[i])] = parts[i + 1].strip()
    if sorted(out) != list(range(count)):
        return None
    return [out[i] for i in range(count)]


def translate_many(texts: list[str], code: str) -> list[str]:
    """Перевести список текстов. Порядок сохраняется. Пустые остаются пустыми."""
    result = [""] * len(texts)
    todo = [(i, t.strip()) for i, t in enumerate(texts) if t and t.strip()]
    batch: list[tuple[int, str]] = []

    def flush() -> None:
        if not batch:
            return
        joined = "".join(SEP.format(n=k) + text for k, (_, text) in enumerate(batch))
        parts = None
        if len(batch) > 1:
            try:
                parts = _split(translate_one(joined, code), len(batch))
            except TranslateError:
                parts = None
        if parts is None:
            # Пачка не разобралась (сервис тронул разделитель) — по одному.
            parts = [translate_one(text, code) for _, text in batch]
        for (index, _), part in zip(batch, parts):
            result[index] = part
        batch.clear()

    size = 0
    for index, text in todo:
        if batch and size + len(text) > BATCH_CHARS:
            flush()
            size = 0
        batch.append((index, text))
        size += len(text) + 12
    flush()
    return result
