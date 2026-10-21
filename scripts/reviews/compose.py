"""Тема отзыва и варианты ответа из банка фраз — без нейросети.

Ответ собирается из кусков: обращение + сочувствие или благодарность + суть по
теме + совет + концовка. Каждый кусок есть на английском и русском. Три
варианта под одним отзывом берут разные куски, а суть, уже ушедшую в
отправленных ответах этого приложения, повторно не берут, пока есть другие.

Тема — по ключевым словам английского текста (отзыв на другом языке сначала
переводится). Более длинная фраза весит больше одного слова: «lost my
subscription» должна побеждать «lost».
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

BANK_DIR = Path(__file__).resolve().parent / "bank"

# Темы-жалобы не годятся для похвалы и наоборот.
POSITIVE_ONLY = {"praise", "general_pos"}
FALLBACK = {"neg": "general_neg", "mid": "general_mid", "pos": "general_pos"}

STYLES = [
    # (код, подпись в консоли, какие куски брать)
    ("full", "Подробно", ("opener", "empathy", "core", "advice", "closer")),
    ("short", "Коротко", ("opener", "core", "closer")),
    ("warm", "С сочувствием" , ("opener", "empathy", "core", "closer")),
]
STYLE_LABEL_POS = {"warm": "Тепло"}


@dataclass
class Bank:
    common: dict
    topics: dict

    @classmethod
    def load(cls, directory: Path = BANK_DIR) -> "Bank":
        common = json.loads((directory / "common.json").read_text(encoding="utf-8"))
        topics: dict = {}
        for path in sorted(directory.glob("topics*.json")):
            topics.update(json.loads(path.read_text(encoding="utf-8"))["topics"])
        return cls(common=common, topics=topics)


def band(rating: int) -> str:
    return "neg" if rating <= 2 else "mid" if rating == 3 else "pos"


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("’", "'")) + " "


def classify(bank: Bank, english: str, rating: int) -> str:
    text = _norm(english)
    b = band(rating)
    best, best_score = None, 0.0
    for key, topic in bank.topics.items():
        if b != "pos" and key in POSITIVE_ONLY:
            continue
        score = 0.0
        for word in topic.get("keywords", []):
            if _norm(word) in text:
                score += len(word.split())
        # Похвала с хорошей оценкой — частый случай; при равенстве уступает
        # конкретной теме (5★ «люблю, но добавьте X» — это просьба).
        if key == "praise":
            score -= 0.5
        if score > best_score:
            best, best_score = key, score
    return best or FALLBACK[b]


def _fill(text: str, app: str) -> str:
    return text.replace("{app}", app)


def compose(bank: Bank, *, review_id: str, rating: int, topic: str, app: str,
            used: set[str] | None = None, exclude: set[str] | None = None,
            count: int = 3) -> list[dict]:
    """Варианты ответа. used — суть, уже отправленная в этом приложении;
    exclude — куски, уже показанные под этим отзывом (для «ещё вариантов»)."""
    used = used or set()
    exclude = set(exclude or ())
    b = band(rating)
    t = bank.topics[topic]
    rng = random.Random(f"{review_id}:{len(exclude)}")

    def pick(pool: list[dict], *, avoid_used: bool = False) -> dict | None:
        fresh = [p for p in pool if p["id"] not in exclude]
        if avoid_used:
            unused = [p for p in fresh if p["id"] not in used]
            fresh = unused or fresh
        if not fresh:
            fresh = list(pool)
        if not fresh:
            return None
        choice = rng.choice(fresh)
        exclude.add(choice["id"])
        return choice

    out = []
    for code, label, parts in STYLES[:count] if count <= len(STYLES) else STYLES:
        pieces = []
        for part in parts:
            if part == "core":
                piece = pick(t["core"], avoid_used=True)
            elif part == "advice":
                piece = pick(t.get("advice", [])) if t.get("advice") else None
            else:
                piece = pick(bank.common[part][b])
            if piece:
                pieces.append(piece)
        out.append({
            "style": code,
            "label": STYLE_LABEL_POS.get(code, label) if b == "pos" else label,
            "en": _fill(" ".join(p["en"] for p in pieces), app),
            "ru": _fill(" ".join(p["ru"] for p in pieces), app),
            "parts": [p["id"] for p in pieces],
        })
    return out


def core_of(parts: list[str]) -> str | None:
    """Какая «суть» в ответе — её и помним как использованную."""
    for part in parts:
        if ".c" in part:
            return part
    return None
