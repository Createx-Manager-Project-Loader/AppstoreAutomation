#!/usr/bin/env python3
"""Пример reviews.json для проверки вкладки «Отзывы» на своей машине.

Отзывы придуманы, всё остальное — настоящее: язык, перевод нашим сервисом,
тема и варианты из банка. Apple не трогается.

  TRANSLATOR_URL=… TRANSLATOR_TOKEN=… python3 make_fixture.py out.json
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import compose  # noqa: E402
import reviews  # noqa: E402

NOW = datetime.now(timezone.utc)

SAMPLE = [
    (2, "Doesn't translate anything", "I recorded my dog barking ten times and it just shows \"hungry\" with 40%. Paid for the week.", "USA", 1),
    (1, "Abo nicht kündbar", "Ich finde nicht, wo man das Abo beendet. Bitte erklären.", "DEU", 2),
    (3, "Muy lento", "Tarda mucho en analizar el sonido.", "MEX", 4),
    (5, "Fun with my corgi", "Works better after I labelled a few sounds myself. Would love more categories.", "GBR", 5),
    (1, "Вылетает", "Приложение закрывается каждый раз, когда начинаю запись.", "KAZ", 6),
    (2, "録音が保存されない", "アプリを再起動すると、ラベルを付けた音がすべて消えます。", "JPN", 8),
    (4, "Sympa", "L'application est amusante, mais il y a trop de publicités.", "FRA", 9),
    (1, "Charged after trial", "I cancelled the trial and still got charged. Scam!", "USA", 12),
    (5, "Love it", "My kids play with it every evening.", "CAN", 15),
    (2, "Já paguei", "Já paguei a assinatura mas o app ainda pede para pagar.", "BRA", 20),
    (5, "Отличное приложение", "Собака теперь «разговаривает» :)", "RUS", 26),
    (3, "Ok", "Nice idea, could be more accurate.", "AUS", 40),
]


def main() -> int:
    out = Path(sys.argv[1])
    fresh = []
    for i, (rating, title, body, territory, days) in enumerate(SAMPLE):
        fresh.append({
            "id": f"sample-{i + 1:02d}", "rating": rating, "title": title, "body": body,
            "nickname": f"user{i}", "territory": territory,
            "createdAt": (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "response": None,
        })
    # Два отзыва уже с ответом — для состояний «на модерации» и «опубликован».
    fresh[8]["response"] = {"id": "r1", "body": "Thank you! Glad your kids enjoy it.", "state": "PENDING_PUBLISH", "at": reviews.now()}
    fresh[10]["response"] = {"id": "r2", "body": "Спасибо! Рады, что вам нравится.", "state": "PUBLISHED", "at": reviews.now()}

    warnings: list[str] = []
    reviews.add_translations(fresh, warnings)
    bank = compose.Bank.load()
    for review in fresh:
        if review["response"]:
            review["topic"] = compose.classify(bank, review.get("en") or reviews.text_of(review), review["rating"])
            review["topicLabel"] = bank.topics[review["topic"]]["label"]
        else:
            review["variants"] = reviews.draft(bank, review, "Dog Translator", set(), warnings)
    state = {"version": reviews.STATE_VERSION, "app": {"id": "0", "name": "Dog Translator"}, "reviews": fresh,
             "used": [], "collectedAt": reviews.now(), "collectedBy": "local",
             "lastCollect": {"at": "2000-01-01T00:00:00Z", "new": len(fresh), "unanswered": 10, "seconds": 40, "warnings": warnings}}
    reviews.save_state(out, state)
    print(f"{out}: {len(fresh)} отзывов; предупреждения: {warnings or 'нет'}")
    for r in fresh:
        print(f"  {r['rating']}★ {r['territory']} {r.get('lang')} {r.get('topic')} | {r.get('ru') and r['ru'].get('title')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
