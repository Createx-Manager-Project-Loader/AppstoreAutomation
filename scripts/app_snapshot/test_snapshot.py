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

# Языки: один язык не прочитался — раздел собран, язык помечен.
class Flaky(Fake):
    def request(self, method: str, path: str) -> dict:
        if "/l2/appScreenshotSets" in path:
            raise RuntimeError("GET https://api.appstoreconnect.apple.com/... failed: Read timed out. (read timeout=60)")
        return super().request(method, path)


client = Flaky(client.routes)
sec = snapshot.section_languages(client, APP, {}, None)
de = next(l for l in sec["locales"] if l["locale"] == "de-DE")
check("языки: de не прочитан, en на месте", de["screenshots"] is None and sec["unread"] == [{"locale": "de-DE", "kind": "timeout"}])


class Dead(Fake):
    def request(self, method: str, path: str) -> dict:
        if "appScreenshotSets" in path:
            raise RuntimeError("Read timed out")
        return super().request(method, path)


try:
    snapshot.section_languages(Dead(client.routes), APP, {}, None)
    check("языки: ни один не прочитан — ошибка раздела", False)
except snapshot.SectionError as error:
    check("языки: ни один не прочитан — ошибка раздела", error.kind == "timeout")

# Причины ошибок.
for text, kind in [("Read timed out. (read timeout=60)", "timeout"), ("GET /x failed with 429: {}", "rate"),
                   ("GET /x failed with 401: {}", "auth"), ("GET /x failed with 404: {}", "notfound"),
                   ("GET /x failed with 503: {}", "apple"), ("что-то странное", "other")]:
    check(f"причина: {kind}", snapshot.kind_of(RuntimeError(text)) == kind)

# Запись раздела: при ошибке старые данные и их дата остаются.
good = snapshot.record_section(None, "t1", data={"x": 1})
bad = snapshot.record_section(good, "t2", error=RuntimeError("Read timed out"))
check("ошибка: данные и dataAt от прошлого раза", bad["data"] == {"x": 1} and bad["dataAt"] == "t1" and bad["at"] == "t2")
bad2 = snapshot.record_section(bad, "t3", error=RuntimeError("GET failed with 503"))
check("ошибка подряд: dataAt не сдвигается", bad2["dataAt"] == "t1" and bad2["errorKind"] == "apple")
check("старый формат без dataAt: берём at", snapshot.record_section({"at": "t0", "data": 1, "error": None}, "t4", error=RuntimeError("x"))["dataAt"] == "t0")
check("ошибка без прошлых данных: dataAt пуст", snapshot.record_section(None, "t5", error=RuntimeError("x"))["dataAt"] is None)

# Тексты: название с appInfo (редактируемого), описание и ключи с версии — в одну строку по языку.
APP_L = {"id": "1", "attributes": {"name": "Locator 54", "primaryLocale": "en-US"}}
client = Fake({
    "/apps/1/appStoreVersions": {"data": [V("1.13", "PREPARE_FOR_SUBMISSION", "2026-10-20")]},
    "/apps/1/appInfos": {"data": [{"id": "live", "attributes": {"state": "READY_FOR_DISTRIBUTION"}},
                                  {"id": "edit", "attributes": {"state": "PREPARE_FOR_SUBMISSION"}}]},
    "/appInfos/edit/appInfoLocalizations": {"data": [{"attributes": {"locale": "en-US", "name": "Locator", "subtitle": "Find family"}}]},
    "/appStoreVersions/v1.13/appStoreVersionLocalizations": {"data": [
        {"attributes": {"locale": "en-US", "description": "Long text", "keywords": "gps,map", "whatsNew": "Fixes"}},
        {"attributes": {"locale": "de-DE", "description": "Lang", "keywords": "karte"}}]},
})
sec = snapshot.section_listing(client, APP_L, {}, None)
en = next(l for l in sec["locales"] if l["locale"] == "en-US")
de = next(l for l in sec["locales"] if l["locale"] == "de-DE")
check("тексты: en собран из двух мест", en["name"] == "Locator" and en["subtitle"] == "Find family" and en["keywords"] == "gps,map")
check("тексты: de без названия — пусто, но язык есть", de["name"] is None and de["description"] == "Lang")
check("тексты: взят редактируемый appInfo", not any("/appInfos/live/" in a for a in client.asked))
check("тексты: версия и основной язык", sec["version"] == "1.13" and sec["primaryLocale"] == "en-US")

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
