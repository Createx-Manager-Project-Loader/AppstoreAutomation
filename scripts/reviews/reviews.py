#!/usr/bin/env python3
"""Отзывы App Store: сбор, ответы, новые варианты — для вкладки «Отзывы».

Консоль сама в Apple не ходит: ключи лежат в секретах репозитория приложения.
Всё делает этот скрипт в прогоне GitHub Actions, а итог кладёт в
reviews/reviews.json того же репозитория. Консоль читает этот файл.

Действия:
  collect — забрать новые отзывы и наши ответы, перевести, подобрать варианты;
  reply   — отправить пачку ответов (план из консоли);
  more    — ещё три варианта для одного отзыва.

Сбор только по кнопке в консоли: ни расписания, ни массового прохода по
всем приложениям (решение владельца, 21 октября — чтобы не было резкого
всплеска запросов по аккаунтам).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "lib"))

import compose  # noqa: E402
import lang  # noqa: E402
from translate import TranslateError, translate_many  # noqa: E402

STATE_VERSION = 1
# Храним последние отзывы: старые ни сводке, ни ответам не нужны.
KEEP_REVIEWS = 1000
# Сколько отзывов без ответа получают варианты за один сбор: у старого
# приложения их может быть сотни, а ответы нужны свежим.
DRAFT_LIMIT = 60
# Длина ответа по правилам Apple.
RESPONSE_LIMIT = 5970


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    print(message, flush=True)


# ── состояние ─────────────────────────────────────────────────────────────

def load_state(path: Path) -> dict:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") == STATE_VERSION:
            return data
    return {"version": STATE_VERSION, "reviews": [], "used": [], "collectedAt": None}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["reviews"] = sorted(state["reviews"], key=lambda r: r["createdAt"], reverse=True)[:KEEP_REVIEWS]
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ── Apple ─────────────────────────────────────────────────────────────────

def response_of(included: dict, review: dict) -> dict | None:
    rel = (review.get("relationships") or {}).get("response", {}).get("data")
    if not rel:
        return None
    item = included.get(("customerReviewResponses", rel["id"]))
    if not item:
        return {"id": rel["id"], "body": "", "state": "UNKNOWN", "at": None}
    a = item["attributes"]
    return {"id": item["id"], "body": a.get("responseBody", ""), "state": a.get("state", "UNKNOWN"),
            "at": a.get("lastModifiedDate")}


def fetch_reviews(client, app_id: str, known: set[str]) -> tuple[list[dict], dict]:
    """Новые отзывы, от свежих к старым, до первого уже известного.
    Второе — ответы, которые Apple вернул вместе со страницами."""
    path = (f"/apps/{app_id}/customerReviews?sort=-createdDate&limit=200"
            "&include=response&fields[customerReviewResponses]=responseBody,lastModifiedDate,state")
    fresh: list[dict] = []
    responses: dict = {}
    while path:
        page = client.request("GET", path)
        included = {(i["type"], i["id"]): i for i in page.get("included", [])}
        stop = False
        for item in page.get("data", []):
            responses[item["id"]] = response_of(included, item)
            if item["id"] in known:
                stop = True
                continue
            a = item["attributes"]
            fresh.append({
                "id": item["id"],
                "rating": int(a.get("rating") or 0),
                "title": (a.get("title") or "").strip(),
                "body": (a.get("body") or "").strip(),
                "nickname": a.get("reviewerNickname") or "",
                "territory": a.get("territory") or "",
                "createdAt": a.get("createdDate") or now(),
            })
        path = None if stop else page.get("links", {}).get("next")
    return fresh, responses


def refresh_pending(client, state: dict, seen: dict) -> None:
    """Ответы на модерации у старых отзывов: страницы до них могли не дойти."""
    for review in state["reviews"]:
        if review["id"] in seen:
            # Apple вернул отзыв вместе с ответом — это и есть свежее состояние.
            review["response"] = seen[review["id"]]
            continue
        resp = review.get("response")
        if resp and resp.get("state") == "PENDING_PUBLISH":
            try:
                item = client.request("GET", f"/customerReviews/{review['id']}/response")["data"]
                a = item["attributes"]
                review["response"] = {"id": item["id"], "body": a.get("responseBody", ""),
                                      "state": a.get("state", "UNKNOWN"), "at": a.get("lastModifiedDate")}
            except Exception as error:  # noqa: BLE001 — статус догонит следующий сбор
                log(f"WARNING: статус ответа на {review['id']} не прочитан: {error}")


# ── перевод и варианты ───────────────────────────────────────────────────

def text_of(review: dict) -> str:
    return "\n".join(x for x in (review.get("title"), review.get("body")) if x)


def add_translations(fresh: list[dict], warnings: list[str]) -> None:
    """Каждому новому отзыву — язык, английский текст (для темы) и русский."""
    for review in fresh:
        review["lang"] = lang.guess(text_of(review), review["territory"])
    need_en = [r for r in fresh if r["lang"] != "EN"]
    need_ru = [r for r in fresh if r["lang"] != "RU"]
    try:
        en = translate_many([text_of(r) for r in need_en], "EN-US")
        for review, text in zip(need_en, en):
            review["en"] = text
            # Латиница из «неанглийской» страны, а перевод совпал — значит,
            # писали по-английски.
            if lang.is_english(text_of(review), text):
                review["lang"] = "EN"
        ru_titles = translate_many([r["title"] for r in need_ru], "RU")
        ru_bodies = translate_many([r["body"] for r in need_ru], "RU")
        for review, title, body in zip(need_ru, ru_titles, ru_bodies):
            review["ru"] = {"title": title, "body": body}
    except TranslateError as error:
        warnings.append(f"перевод: {error}")
        log(f"WARNING: сервис перевода не ответил — отзывы без перевода ({error})")
    for review in fresh:
        if review["lang"] == "EN":
            review["en"] = text_of(review)
        if review["lang"] == "RU":
            review["ru"] = None


def localize(variants: list[dict], target: str, warnings: list[str]) -> None:
    """Текст варианта на языке отзыва. Английский и русский уже есть в банке."""
    for v in variants:
        if target == "EN":
            v["text"] = v["en"]
        elif target == "RU":
            v["text"] = v["ru"]
    todo = [v for v in variants if "text" not in v]
    if not todo:
        return
    try:
        for v, text in zip(todo, translate_many([v["en"] for v in todo], target)):
            v["text"] = text
    except TranslateError as error:
        warnings.append(f"перевод вариантов: {error}")
        for v in todo:
            v["text"] = v["en"]
            v["untranslated"] = True


def draft(bank, review: dict, app: str, used: set[str], warnings: list[str], exclude=None) -> list[dict]:
    topic = review.get("topic") or compose.classify(bank, review.get("en") or text_of(review), review["rating"])
    review["topic"] = topic
    review["topicLabel"] = bank.topics[topic]["label"]
    variants = compose.compose(bank, review_id=review["id"], rating=review["rating"], topic=topic,
                               app=app, used=used, exclude=exclude)
    localize(variants, review.get("lang", "EN"), warnings)
    return variants


# ── действия ─────────────────────────────────────────────────────────────

def client_and_app():
    from upload_screenshots_api import AppStoreConnectClient, find_app, require_env

    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=Path(require_env("ASC_KEY_PATH")),
    )
    app = find_app(client, require_env("APP_IDENTIFIER"))
    return client, app


def app_name(app: dict) -> str:
    return (app.get("attributes") or {}).get("name") or os.environ.get("APP_NAME", "the app")


def do_collect(state: dict, args) -> int:
    client, app = client_and_app()
    name = app_name(app)
    state["app"] = {"id": app["id"], "name": name}
    started = time.time()

    log("ШАГ 1/3 Отзывы из App Store")
    known = {r["id"] for r in state["reviews"]}
    fresh, seen = fetch_reviews(client, app["id"], known)
    log(f"Новых отзывов: {len(fresh)}")
    refresh_pending(client, state, seen)
    for review in fresh:
        review["response"] = seen.get(review["id"])

    warnings: list[str] = []
    log("ШАГ 2/3 Перевод на русский")
    add_translations(fresh, warnings)

    log("ШАГ 3/3 Варианты ответа")
    bank = compose.Bank.load()
    used = set(state.get("used", []))
    unanswered = [r for r in fresh if not r.get("response")][:DRAFT_LIMIT]
    for review in fresh:
        if review not in unanswered:
            review.setdefault("topic", compose.classify(bank, review.get("en") or text_of(review), review["rating"]))
            review["topicLabel"] = bank.topics[review["topic"]]["label"]
    for review in unanswered:
        review["variants"] = draft(bank, review, name, used, warnings)

    state["reviews"] = fresh + state["reviews"]
    state["collectedAt"] = now()
    state["collectedBy"] = os.environ.get("REVIEWS_ACTOR", "")
    state["lastCollect"] = {"at": state["collectedAt"], "new": len(fresh),
                            "unanswered": len(unanswered), "seconds": round(time.time() - started),
                            "warnings": warnings}
    log(f"Готово: новых {len(fresh)}, без ответа {len(unanswered)}"
        + (f"; предупреждения: {'; '.join(warnings)}" if warnings else ""))
    return 0


def do_reply(state: dict, args) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    items = plan.get("replies", [])
    if not items:
        log("ERROR: в плане нет ответов")
        return 1
    client, app = client_and_app()
    by_id = {r["id"]: r for r in state["reviews"]}
    used = set(state.get("used", []))
    sent, failed = [], []
    for item in items:
        review_id, text = item["id"], (item.get("text") or "").strip()
        if not text or len(text) > RESPONSE_LIMIT:
            failed.append({"id": review_id, "reason": "пустой ответ или длиннее 5 970 знаков"})
            continue
        body = {"data": {"type": "customerReviewResponses",
                         "attributes": {"responseBody": text},
                         "relationships": {"review": {"data": {"type": "customerReviews", "id": review_id}}}}}
        try:
            data = client.request("POST", "/customerReviewResponses", json=body)["data"]
            a = data.get("attributes", {})
            response = {"id": data["id"], "body": a.get("responseBody", text),
                        "state": a.get("state", "PENDING_PUBLISH"), "at": a.get("lastModifiedDate") or now(),
                        "by": item.get("by", "")}
            sent.append(review_id)
            log(f"ОТПРАВЛЕН {review_id}")
            if review_id in by_id:
                by_id[review_id]["response"] = response
                core = compose.core_of(item.get("parts") or [])
                if core:
                    used.add(core)
        except Exception as error:  # noqa: BLE001 — один отказ не отменяет остальные
            reason = str(error)
            short = ("отзыв удалён автором или недоступен" if " 404" in reason
                     else "у ключа нет прав на ответы" if " 403" in reason
                     else "Apple не принял ответ")
            failed.append({"id": review_id, "reason": short})
            log(f"НЕ ОТПРАВЛЕН {review_id}: {reason[:300]}")
    state["used"] = sorted(used)
    state["lastReply"] = {"at": now(), "by": os.environ.get("REVIEWS_ACTOR", ""), "sent": sent, "failed": failed}
    log(f"Отправлено {len(sent)} из {len(items)}")
    return 0 if not failed else 2


def do_more(state: dict, args) -> int:
    review = next((r for r in state["reviews"] if r["id"] == args.review), None)
    if not review:
        log(f"ERROR: отзыва {args.review} нет в собранных")
        return 1
    _, app = client_and_app()
    bank = compose.Bank.load()
    shown = {p for v in review.get("variants", []) for p in v.get("parts", [])}
    warnings: list[str] = []
    review["variants"] = review.get("variants", []) + draft(
        bank, review, app_name(app), set(state.get("used", [])), warnings, exclude=shown)
    log(f"Вариантов теперь: {len(review['variants'])}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["collect", "reply", "more"])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--review")
    args = parser.parse_args()

    state = load_state(args.state)
    code = {"collect": do_collect, "reply": do_reply, "more": do_more}[args.action](state, args)
    save_state(args.state, state)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
