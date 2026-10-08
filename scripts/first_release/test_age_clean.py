"""Анкета рейтинга: в Apple уезжают только его ключи (живой случай CarPlay2)."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from setup_app import AGE_BOOL, AGE_LEVEL, clean_answers  # noqa: E402

carplay = yaml.safe_load("""
violenceCartoonOrFantasy: NONE
contests: none
gambling: false
unrestrictedWebAccess: false
"In-app AI chatbot / generated content": YES
notes: "Chat is between the user and a language model only."
advertising: "YES"
lootBox: maybe
""")
clean, notes = clean_answers(carplay)
full, full_notes = clean_answers({**{k: False for k in AGE_BOOL}, **{k: "NONE" for k in AGE_LEVEL}})

checks = [
    ("чужие ключи не уезжают", "notes" not in clean and not any("chatbot" in k for k in clean)),
    ("и названы в отчёте", any("отброшены" in n and "notes" in n for n in notes)),
    ("частота в любом регистре", clean["contests"] == "NONE"),
    ("YES строкой → true", clean["advertising"] is True),
    ("непонятный ответ не уезжает", "lootBox" not in clean),
    ("непонятный ответ назван", any("lootBox" in n for n in notes)),
    ("неотвеченные посчитаны", any("без ответа" in n for n in notes)),
    ("полная анкета — без замечаний", len(full) == 24 and not full_notes),
]
ok = True
for label, cond in checks:
    ok &= cond
    print(("OK   " if cond else "ПЛОХО") + " " + label)
sys.exit(0 if ok else 1)
