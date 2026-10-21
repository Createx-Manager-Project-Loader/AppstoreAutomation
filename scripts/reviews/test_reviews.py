#!/usr/bin/env python3
"""Отзывы: язык, тема, варианты, разбор пачки перевода, банк по правилам."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import compose  # noqa: E402
import lang  # noqa: E402
import translate  # noqa: E402

ok = True


def check(label: str, cond: bool) -> None:
    global ok
    ok = ok and cond
    print(("OK   " if cond else "ПЛОХО") + " " + label)


# Язык
check("немецкий по стране", lang.guess("Ich finde nicht", "DEU") == "DE")
check("кириллица из Казахстана — русский", lang.guess("Отлично", "KAZ") == "RU")
check("украинские буквы", lang.guess("Додаток дуже повільний, ї", "KAZ") == "UK")
check("японский из одних иероглифов", lang.guess("最高", "JPN") == "JA")
check("китайский", lang.guess("应用太慢了", "CHN") == "ZH-HANS")
check("английский из Германии", lang.is_english("Great app, love it", "Great app, love it"))
check("немецкий не английский", not lang.is_english("Ich finde nicht", "I can't find"))

# Тема
bank = compose.Bank.load()
check("отмена подписки", compose.classify(bank, "Can't find where to cancel the subscription", 1) == "subscription_cancel")
check("вылет", compose.classify(bank, "App crashes every time", 1) == "crash")
check("восстановление сильнее «lost»", compose.classify(bank, "I lost my subscription, paid but still asks to pay", 1) == "restore")
check("5★ с просьбой — просьба", compose.classify(bank, "Love it! Would be great to add more", 5) == "feature_request")
check("похвала", compose.classify(bank, "Love it, amazing", 5) == "praise")
check("плохо без слов — общая", compose.classify(bank, "meh", 1) == "general_neg")
check("похвала не для 1★", compose.classify(bank, "great idea but", 1) != "praise")

# Варианты
v = compose.compose(bank, review_id="x", rating=1, topic="crash", app="Dog Translator")
check("три варианта", len(v) == 3)
cores = [compose.core_of(x["parts"]) for x in v]
check("суть у вариантов разная", len(set(cores)) == 3)
parts = [p for x in v for p in x["parts"]]
check("куски не повторяются между вариантами", len(parts) == len(set(parts)))
check("название подставлено", all("{app}" not in x["en"] and "{app}" not in x["ru"] for x in v))
used = {"cr.c1", "cr.c2", "cr.c3"}
v2 = compose.compose(bank, review_id="y", rating=1, topic="crash", app="A", used=used, count=1)
check("отправленная суть не повторяется", compose.core_of(v2[0]["parts"]) not in used)
more = compose.compose(bank, review_id="x", rating=1, topic="crash", app="A", exclude=set(parts))
check("ещё варианты — другие куски", not (set(p for x in more for p in x["parts"]) & set(parts)) or len(bank.topics["crash"]["core"]) < 6)

# Пачка перевода
joined = "⟦0⟧\n\nПривет\n\n⟦1⟧\n\nМир"
check("пачка разбирается", translate._split(joined, 2) == ["Привет", "Мир"])
check("перепутанная пачка не принимается", translate._split("⟦0⟧ a ⟦0⟧ b", 2) is None)
check("английский — с регионом", translate.target_code("EN") == "EN-US")

# Банк по правилам: без возвратов, ссылок, сроков; у каждого куска есть русский
banned = re.compile(r"refund|money back|https?://|\.com\b|next update|soon|within \d|возврат|верн[её]м деньги", re.I)
pieces = []
common = json.loads((HERE / "bank/common.json").read_text())
for group in ("opener", "empathy", "closer"):
    for b in ("neg", "mid", "pos"):
        pieces += common[group][b]
for t in bank.topics.values():
    pieces += t["core"] + t.get("advice", [])
check("у каждого куска есть ru", all(p.get("ru") and p.get("en") for p in pieces))
check("id не повторяются", len({p["id"] for p in pieces}) == len(pieces))
bad = [p["id"] for p in pieces if banned.search(p["en"]) or banned.search(p["ru"])]
check(f"нет запрещённого ({', '.join(bad) or '—'})", not bad)

sys.exit(0 if ok else 1)
