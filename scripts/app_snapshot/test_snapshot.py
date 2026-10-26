#!/usr/bin/env python3
"""Снимок из App Store Connect: разделы на поддельном клиенте, без запросов к Apple."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import snapshot  # noqa: E402

ok = True


def check(label: str, cond: bool) -> None:
    global ok
    ok = ok and cond
    print(("OK   " if cond else "ПЛОХО") + " " + label)


def ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S-07:00")


class Fake:
    """Отвечает по началу пути; запоминает, о чём спрашивали."""

    def __init__(self, routes: dict[str, dict]):
        self.routes, self.asked = routes, []

    def request(self, method: str, path: str) -> dict:
        self.asked.append(path)
        for prefix, payload in self.routes.items():
            if path.startswith(prefix):
                return payload
        raise AssertionError(f"неожиданный запрос {path}")


APP = {"id": "1", "attributes": {"name": "Locator 54", "bundleId": "com.loc", "sku": "loc54"}}
V = lambda v, s, d: {"id": f"v{v}", "attributes": {"versionString": v, "appStoreState": s, "createdDate": d, "releaseType": "MANUAL"}}  # noqa: E731

# Статус и версии.
client = Fake({"/apps/1/appStoreVersions": {"data": [V("1.12", "READY_FOR_SALE", "2026-10-01"), V("1.13", "IN_REVIEW", "2026-10-20")]}})
sec = snapshot.section_status(client, APP, {}, "pm")
check("статус: на проверке, в продаже 1.12", sec["status"] == "review" and sec["live"] == "1.12" and sec["appVersion"] == "1.13")
check("статус: версии от новой к старой", [v["version"] for v in sec["versions"]] == ["1.13", "1.12"])
check("статус: история с первой записью", len(sec["history"]) == 1)

# Отзывы: только 30 дней, без ответа считаются.
client = Fake({"/apps/1/customerReviews": {"data": [
    {"attributes": {"rating": 5, "createdDate": ago(1)}, "relationships": {"response": {"data": {"id": "r"}}}},
    {"attributes": {"rating": 1, "createdDate": ago(3)}, "relationships": {"response": {"data": None}}},
    {"attributes": {"rating": 4, "createdDate": ago(10)}, "relationships": {}},
    {"attributes": {"rating": 2, "createdDate": ago(45)}, "relationships": {}},
], "links": {"next": "/apps/1/customerReviews?page=2"}}})
sec = snapshot.section_reviews(client, APP, {}, None)
check("отзывы: три за 30 дней", sec["count"] == 3 and sec["byStar"]["5"] == 1 and sec["byStar"]["2"] == 0)
check("отзывы: средняя", sec["average"] == round(10 / 3, 2))
check("отзывы: без ответа — два", sec["unanswered"] == 2)
check("отзывы: старше 30 дней — дальше не листаем", len(client.asked) == 1)

# Подписки.
client = Fake({
    "/apps/1/subscriptionGroups": {"data": [{"id": "g1", "attributes": {"referenceName": "Premium"}}]},
    "/subscriptionGroups/g1/subscriptions": {"data": [{"attributes": {"productId": "week", "name": "Week", "state": "APPROVED"}},
                                                      {"attributes": {"productId": "year", "name": "Year", "state": "MISSING_METADATA"}}]},
})
sec = snapshot.section_subscriptions(client, APP, {}, None)
check("подписки: обе с состоянием", [(i["productId"], i["state"]) for i in sec["items"]] == [("week", "APPROVED"), ("year", "MISSING_METADATA")])

# Языки и кадры.
client = Fake({
    "/apps/1/appStoreVersions": {"data": [V("1.13", "IN_REVIEW", "2026-10-20")]},
    "/appStoreVersions/v1.13/appStoreVersionLocalizations": {"data": [
        {"id": "l1", "attributes": {"locale": "en-US", "description": "x", "keywords": "k"}},
        {"id": "l2", "attributes": {"locale": "de-DE", "description": "", "keywords": None}}]},
    "/appStoreVersionLocalizations/l1/appScreenshotSets": {"included": [{"type": "appScreenshots"}] * 6},
    "/appStoreVersionLocalizations/l2/appScreenshotSets": {"included": []},
})
sec = snapshot.section_languages(client, APP, {}, None)
de = next(l for l in sec["locales"] if l["locale"] == "de-DE")
en = next(l for l in sec["locales"] if l["locale"] == "en-US")
check("языки: en с текстом и 6 кадрами", en["text"] and en["screenshots"] == 6)
check("языки: de без текста и кадров", not de["text"] and de["screenshots"] == 0)

# О приложении.
client = Fake({"/apps/1/appInfos": {"data": [{"attributes": {"appStoreAgeRating": "FOUR_PLUS", "state": "READY_FOR_DISTRIBUTION"},
                                              "relationships": {"primaryCategory": {"data": {"id": "NAVIGATION"}}}}]}})
sec = snapshot.section_info(client, APP, {}, None)
check("о приложении: категория и рейтинг", sec["category"] == "NAVIGATION" and sec["ageRating"] == "FOUR_PLUS" and sec["sku"] == "loc54")

# Файл: версия формата и разделы переживают сохранение.
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "store" / "snapshot.json"
    st = snapshot.load(f)
    st["sections"]["status"] = {"at": "t", "data": {"status": "review"}, "error": None}
    snapshot.save(f, st)
    back = snapshot.load(f)
    check("файл: читается обратно", back["version"] == snapshot.STATE_VERSION and back["sections"]["status"]["data"]["status"] == "review")
    f.write_text(json.dumps({"version": 99}))
    check("файл: чужая версия формата — начинаем заново", snapshot.load(f)["sections"] == {})

sys.exit(0 if ok else 1)
