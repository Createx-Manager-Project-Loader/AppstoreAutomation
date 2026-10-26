#!/usr/bin/env python3
"""Снимок приложения из App Store Connect для консоли — «Обновить из App Store Connect».

Одна кнопка в консоли — один прогон: статус и версии, A/B-тесты, отзывы,
подписки, языки и кадры, тексты страницы по языкам, сведения о приложении. Каждый раздел — отдельный
шаг workflow (консоль показывает их как прогресс) и отдельный вызов этого
скрипта: он дописывает свой раздел в store/snapshot.json.

Раздел, который не собрался, получает error с причиной, остальные остаются —
прогон при этом зелёный. Консоль в Apple не ходит, только читает файл.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

import status as status_lib  # noqa: E402

STATE_VERSION = 1
SECTIONS = ("status", "ab", "reviews", "subscriptions", "languages", "listing", "info")
REVIEW_DAYS = 30


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: Path) -> dict:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") == STATE_VERSION:
            return data
    return {"version": STATE_VERSION, "sections": {}}


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ── разделы ────────────────────────────────────────────────────────────────

def versions_of(client, app_id: str) -> list[dict]:
    response = client.request(
        "GET",
        f"/apps/{app_id}/appStoreVersions?filter[platform]=IOS&limit=20"
        "&fields[appStoreVersions]=versionString,appStoreState,appVersionState,createdDate,releaseType",
    )
    return sorted(response.get("data") or [], key=lambda v: (v.get("attributes") or {}).get("createdDate") or "", reverse=True)


def section_status(client, app: dict, prev: dict, by: str | None) -> dict:
    """Статус последней версии, какая в продаже, история смен и последние версии."""
    versions = versions_of(client, app["id"])
    current = status_lib.summarize(versions)
    section = status_lib.record(prev, current, now(), by)
    section["versions"] = [
        {
            "version": (v.get("attributes") or {}).get("versionString"),
            "status": status_lib.status_of(status_lib.raw_state(v)),
            "raw": status_lib.raw_state(v),
            "createdAt": (v.get("attributes") or {}).get("createdDate"),
            "release": (v.get("attributes") or {}).get("releaseType"),
        }
        for v in versions[:5]
    ]
    return section


def section_ab(client, app: dict, prev: dict, by: str | None) -> dict:
    """A/B-тесты страницы App Store — тем же запросом, что и вкладка «A/B-тест»."""
    from ab_test.experiments import Problem, list_experiments  # noqa: WPS433

    try:
        tests = list_experiments(client, app["id"])
    except Problem:
        # Приложения ещё нет в продаже — тестов быть не может, это не ошибка.
        return {"tests": [], "noLiveVersion": True}
    # Целиком, с вариантами: консоль подставляет их в форму заливки кадров.
    return {"tests": tests}


def section_reviews(client, app: dict, prev: dict, by: str | None) -> dict:
    """Сводка отзывов за 30 дней: средняя, распределение, сколько ждут ответа."""
    since = (datetime.now(timezone.utc) - timedelta(days=REVIEW_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    path: str | None = (f"/apps/{app['id']}/customerReviews?sort=-createdDate&limit=200"
                        "&fields[customerReviews]=rating,createdDate,response&include=response"
                        "&fields[customerReviewResponses]=state")
    ratings: list[int] = []
    unanswered = 0
    while path:
        page = client.request("GET", path)
        path = page.get("links", {}).get("next")
        for item in page.get("data", []):
            a = item.get("attributes") or {}
            if (a.get("createdDate") or "") < since:
                path = None
                break
            ratings.append(int(a.get("rating") or 0))
            if not ((item.get("relationships") or {}).get("response") or {}).get("data"):
                unanswered += 1
    by_star = {str(s): ratings.count(s) for s in range(1, 6)}
    return {
        "days": REVIEW_DAYS,
        "count": len(ratings),
        "average": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "byStar": by_star,
        "unanswered": unanswered,
    }


def section_subscriptions(client, app: dict, prev: dict, by: str | None) -> dict:
    """Подписки по группам и их состояние у Apple."""
    groups = client.request("GET", f"/apps/{app['id']}/subscriptionGroups?limit=50").get("data") or []
    out = []
    for group in groups:
        subs = client.request("GET", f"/subscriptionGroups/{group['id']}/subscriptions?limit=100").get("data") or []
        for sub in subs:
            a = sub.get("attributes") or {}
            out.append({"group": (group.get("attributes") or {}).get("referenceName"), "productId": a.get("productId"),
                        "name": a.get("name"), "state": a.get("state")})
    return {"items": out}


def section_languages(client, app: dict, prev: dict, by: str | None) -> dict:
    """Какие тексты и скриншоты заполнены по языкам у последней версии."""
    versions = versions_of(client, app["id"])
    if not versions:
        return {"version": None, "locales": []}
    version = versions[0]
    locs = client.request(
        "GET",
        f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations?limit=200"
        "&fields[appStoreVersionLocalizations]=locale,description,keywords,whatsNew",
    ).get("data") or []
    locales = []
    unread = []
    for loc in locs:
        a = loc.get("attributes") or {}
        # Один язык, на котором Apple не ответил, не должен ронять весь раздел:
        # кадры по нему — «не прочитаны», остальные языки остаются.
        try:
            sets = client.request(
                "GET",
                f"/appStoreVersionLocalizations/{loc['id']}/appScreenshotSets?limit=50"
                "&include=appScreenshots&fields[appScreenshots]=fileName&limit[appScreenshots]=10",
            )
            shots: int | None = sum(1 for i in sets.get("included", []) if i.get("type") == "appScreenshots")
        except Exception as error:  # noqa: BLE001
            shots = None
            unread.append({"locale": a.get("locale"), "kind": kind_of(error)})
        locales.append({"locale": a.get("locale"), "text": bool(a.get("description")), "keywords": bool(a.get("keywords")),
                        "screenshots": shots})
    if locs and len(unread) == len(locs):
        # Не прочитался ни один язык — это уже ошибка раздела, а не частичный ответ.
        raise SectionError(unread[0]["kind"], "скриншоты не прочитаны ни по одному языку")
    return {"version": (version.get("attributes") or {}).get("versionString"),
            "locales": sorted(locales, key=lambda x: x["locale"] or ""), "unread": unread}


LIVE_INFO_STATES = {"READY_FOR_DISTRIBUTION", "READY_FOR_SALE", "REPLACED_WITH_NEW_INFO"}


def section_listing(client, app: dict, prev: dict, by: str | None) -> dict:
    """Тексты страницы в App Store по языкам: название и подзаголовок (appInfo),
    описание, ключевые слова, «Что нового», промо-текст и ссылки (версия).
    Берём то, что сейчас редактируется: новую версию и новый appInfo, если есть."""
    versions = versions_of(client, app["id"])
    version = versions[0] if versions else None
    by_locale: dict[str, dict] = {}

    def slot(locale: str | None) -> dict:
        key = locale or ""
        return by_locale.setdefault(key, {"locale": locale, "name": None, "subtitle": None, "privacyPolicyUrl": None,
                                          "keywords": None, "description": None, "whatsNew": None,
                                          "promotionalText": None, "marketingUrl": None, "supportUrl": None})

    infos = client.request("GET", f"/apps/{app['id']}/appInfos?limit=10").get("data") or []
    # Два appInfo: живой и редактируемый. Показываем редактируемый — он уйдёт в следующую версию.
    editable = [i for i in infos if ((i.get("attributes") or {}).get("state") or (i.get("attributes") or {}).get("appStoreState")) not in LIVE_INFO_STATES]
    info = (editable or infos or [None])[0]
    if info:
        locs = client.request(
            "GET",
            f"/appInfos/{info['id']}/appInfoLocalizations?limit=200"
            "&fields[appInfoLocalizations]=locale,name,subtitle,privacyPolicyUrl",
        ).get("data") or []
        for loc in locs:
            a = loc.get("attributes") or {}
            row = slot(a.get("locale"))
            row.update(name=a.get("name"), subtitle=a.get("subtitle"), privacyPolicyUrl=a.get("privacyPolicyUrl"))

    if version:
        locs = client.request(
            "GET",
            f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations?limit=200"
            "&fields[appStoreVersionLocalizations]=locale,description,keywords,whatsNew,promotionalText,marketingUrl,supportUrl",
        ).get("data") or []
        for loc in locs:
            a = loc.get("attributes") or {}
            row = slot(a.get("locale"))
            row.update(description=a.get("description"), keywords=a.get("keywords"), whatsNew=a.get("whatsNew"),
                       promotionalText=a.get("promotionalText"), marketingUrl=a.get("marketingUrl"), supportUrl=a.get("supportUrl"))

    va = (version or {}).get("attributes") or {}
    return {
        "version": va.get("versionString"),
        "versionState": status_lib.raw_state(version) if version else None,
        "primaryLocale": (app.get("attributes") or {}).get("primaryLocale"),
        "locales": sorted(by_locale.values(), key=lambda x: x["locale"] or ""),
    }


def section_info(client, app: dict, prev: dict, by: str | None) -> dict:
    """Название, категория и возрастной рейтинг."""
    infos = client.request("GET", f"/apps/{app['id']}/appInfos?include=primaryCategory&limit=10").get("data") or []
    info = infos[0] if infos else {}
    a = info.get("attributes") or {}
    category = (((info.get("relationships") or {}).get("primaryCategory") or {}).get("data") or {}).get("id")
    return {
        "appId": app.get("id"),
        "name": (app.get("attributes") or {}).get("name"),
        "bundleId": (app.get("attributes") or {}).get("bundleId"),
        "sku": (app.get("attributes") or {}).get("sku"),
        "category": category,
        "ageRating": a.get("appStoreAgeRating"),
        "state": a.get("state") or a.get("appStoreState"),
    }


HANDLERS = {
    "status": section_status, "ab": section_ab, "reviews": section_reviews,
    "subscriptions": section_subscriptions, "languages": section_languages, "listing": section_listing,
    "info": section_info,
}


class SectionError(RuntimeError):
    """Ошибка раздела с уже известной причиной."""

    def __init__(self, kind: str, text: str):
        super().__init__(text)
        self.kind = kind


# Причины, которые консоль показывает словами: timeout — Apple не ответил вовремя,
# rate — упёрлись в лимит запросов, auth — ключ API не пускает, notfound — Apple
# не нашёл приложение или версию, apple — сбой на стороне Apple, other — прочее.
def kind_of(error: BaseException) -> str:
    if isinstance(error, SectionError):
        return error.kind
    text = f"{type(error).__name__} {error}".lower()
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if " 429" in text or "rate limit" in text:
        return "rate"
    if " 401" in text or " 403" in text or "not authorized" in text or "forbidden" in text:
        return "auth"
    if " 404" in text or "not found" in text:
        return "notfound"
    if any(f" {code}" in text for code in ("500", "502", "503", "504")) or "connection" in text:
        return "apple"
    return "other"


def short(error: BaseException) -> str:
    text = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
    return text[:300]


def record_section(prev: dict | None, at: str, data: Any = None, error: BaseException | None = None) -> dict:
    """Запись раздела. dataAt — когда собраны данные, которые в нём лежат: при ошибке
    прошлые данные остаются, и консоль пишет, от какого они числа."""
    if error is None:
        return {"at": at, "dataAt": at, "data": data, "error": None, "errorKind": None}
    prev = prev or {}
    kept = prev.get("data")
    data_at = (prev.get("dataAt") or (prev.get("at") if not prev.get("error") else None)) if kept is not None else None
    return {"at": at, "dataAt": data_at, "data": kept, "error": short(error), "errorKind": kind_of(error)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--only", required=True, choices=SECTIONS)
    args = parser.parse_args()

    from upload_screenshots_api import AppStoreConnectClient, find_app, require_env

    state = load(args.state)
    sections: dict[str, Any] = state.setdefault("sections", {})
    prev = (sections.get(args.only) or {}).get("data") or {}
    by = os.environ.get("SNAPSHOT_ACTOR")
    try:
        client = AppStoreConnectClient(
            key_id=require_env("ASC_KEY_ID"),
            issuer_id=require_env("ASC_ISSUER_ID"),
            key_path=Path(require_env("ASC_KEY_PATH")),
        )
        app = find_app(client, require_env("APP_IDENTIFIER"))
        data = HANDLERS[args.only](client, app, prev, by)
        sections[args.only] = record_section(sections.get(args.only), now(), data=data)
        print(f"{args.only}: собрано")
    except BaseException as error:  # noqa: BLE001 — раздел не должен ронять прогон
        if isinstance(error, KeyboardInterrupt):
            raise
        # Прошлые данные раздела оставляем: лучше старые, чем пусто.
        sections[args.only] = record_section(sections.get(args.only), now(), error=error)
        print(f"WARNING: {args.only}: не собрано ({kind_of(error)}) — {short(error)}", file=sys.stderr)
    state["updatedAt"] = now()
    state["updatedBy"] = by
    save(args.state, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
