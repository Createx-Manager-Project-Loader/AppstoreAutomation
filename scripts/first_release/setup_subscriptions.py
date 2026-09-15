#!/usr/bin/env python3
"""Заводит подписки первого релиза: группу, продукты, цены, скриншоты для ревью.

Обычные прогоны умеют дописывать локализации к продуктам, которые в App Store
Connect уже есть. Здесь продуктов нет вовсе — их надо создать, и порядок
шагов жёсткий, потому что Apple проверяет зависимости, но не объясняет их:

    группа → локализация группы → продукт → локализация продукта
           → ДОСТУПНОСТЬ ПО СТРАНАМ → цены → скриншот для ревью

**Доступность строго до цены.** Без неё POST цены отвечает 409 «An error
occurred while processing the pricing information» и показывает на ценовую
точку, хотя точка правильная. Выяснено перебором на живом приложении: как
только доступность создана, та же самая точка проходит с первого раза.

**Цена нужна на все страны, а не только на базовую.** Продукт остаётся в
MISSING_METADATA, пока цен меньше, чем стран в доступности. Одна цена в USA
даёт 1 из 175 — остальные берутся из equalizations базовой точки, то есть
из пересчёта, который Apple делает сама.

Готовым считается продукт в состоянии READY_TO_SUBMIT. Прогон проверяет это
чтением обратно и падает, если хоть один продукт не дотянул.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from build_metadata import dig, value_of  # noqa: E402
from setup_app import Problem, read_back, Step  # noqa: E402
from upload_screenshots_api import (  # noqa: E402
    AppStoreConnectClient,
    AppStoreConnectError,
    find_app,
    require_env,
)

# Длительность словами листинга → enum ASC.
PERIODS = {
    "1 week": "ONE_WEEK",
    "1 month": "ONE_MONTH",
    "2 months": "TWO_MONTHS",
    "3 months": "THREE_MONTHS",
    "6 months": "SIX_MONTHS",
    "1 year": "ONE_YEAR",
}

# Сколько цен ставим за раз. Больше упирается в 429 от ASC, меньше — долго:
# 175 стран по одной уходят в три минуты.
PRICE_WORKERS = 6


def period_of(text: str) -> str:
    key = " ".join(str(text).split()).lower().rstrip(".")
    if key in PERIODS:
        return PERIODS[key]
    # «1 years», «one year» и прочее в файл попадает регулярно.
    for name, enum in PERIODS.items():
        if key.replace("s", "") == name.replace("s", ""):
            return enum
    raise Problem(
        f"длительность «{text}» не совпала ни с одной из: {', '.join(PERIODS)}")


class Subscriptions:
    def __init__(self, client: AppStoreConnectClient, app_id: str, listing: dict,
                 locale: str, shots: Path | None) -> None:
        self.client = client
        self.app_id = app_id
        self.listing = listing
        self.locale = locale
        self.shots = shots

    def maybe(self, path: str):
        """GET, который отвечает None вместо исключения на 404.

        Клиент репозитория на 404 бросает AppStoreConnectError, а здесь 404 —
        это нормальный ответ «такого ещё нет»: у нового продукта нет ни
        доступности, ни кадра для ревью.
        """
        try:
            return self.client.request("GET", path)
        except AppStoreConnectError as error:
            if " 404:" in str(error) or "with 404" in str(error):
                return None
            raise

    # ── группа ────────────────────────────────────────────────────────────

    def group(self, name: str) -> str:
        """Ищет группу по имени, создаёт если нет. Повторный прогон не плодит."""
        for existing in self.client.get_all(f"/apps/{self.app_id}/subscriptionGroups?limit=50"):
            if existing["attributes"].get("referenceName") == name:
                return existing["id"]

        created = self.client.request("POST", "/subscriptionGroups", json={"data": {
            "type": "subscriptionGroups",
            "attributes": {"referenceName": name},
            "relationships": {"app": {"data": {"type": "apps", "id": self.app_id}}}}})
        return created["data"]["id"]

    def group_localization(self, group_id: str, name: str) -> None:
        for existing in self.client.get_all(
                f"/subscriptionGroups/{group_id}/subscriptionGroupLocalizations?limit=50"):
            if existing["attributes"].get("locale") == self.locale:
                return
        self.client.request("POST", "/subscriptionGroupLocalizations", json={"data": {
            "type": "subscriptionGroupLocalizations",
            "attributes": {"name": name, "locale": self.locale},
            "relationships": {"subscriptionGroup": {
                "data": {"type": "subscriptionGroups", "id": group_id}}}}})

    # ── продукт ───────────────────────────────────────────────────────────

    def product(self, group_id: str, product: dict, notes: str | None) -> str:
        product_id = product["product_id"]

        # Ищем по ВСЕМ группам приложения, а не только по целевой: product id
        # уникален в пределах приложения, и продукт мог быть заведён раньше в
        # соседней группе. Найдя, переиспользуем — плодить дубль всё равно
        # не дадут.
        for group in self.client.get_all(f"/apps/{self.app_id}/subscriptionGroups?limit=50"):
            for existing in self.client.get_all(
                    f"/subscriptionGroups/{group['id']}/subscriptions?limit=100"):
                if existing["attributes"].get("productId") == product_id:
                    if group["id"] != group_id:
                        print(f"    продукт уже есть в группе "
                              f"«{group['attributes'].get('referenceName')}» — беру его")
                    return existing["id"]

        attributes = {
            "name": product["display_name"],
            "productId": product_id,
            "subscriptionPeriod": product["period"],
            "familySharable": False,
        }
        if notes:
            attributes["reviewNote"] = notes

        try:
            created = self.client.request("POST", "/subscriptions", json={"data": {
                "type": "subscriptions",
                "attributes": attributes,
                "relationships": {"group": {
                    "data": {"type": "subscriptionGroups", "id": group_id}}}}})
        except AppStoreConnectError as error:
            if "already been used" in str(error):
                # Apple не возвращает product id в оборот даже после удаления
                # продукта. Проверено: удалённый id создать заново нельзя.
                raise Problem(
                    f"product id «{product_id}» уже занят в этом приложении и вернуть его "
                    "нельзя — Apple не отдаёт идентификатор обратно даже после удаления "
                    "продукта. Нужен другой id в файле листинга") from error
            raise
        return created["data"]["id"]

    def localization(self, sub_id: str, product: dict) -> None:
        for existing in self.client.get_all(
                f"/subscriptions/{sub_id}/subscriptionLocalizations?limit=50"):
            if existing["attributes"].get("locale") == self.locale:
                return
        self.client.request("POST", "/subscriptionLocalizations", json={"data": {
            "type": "subscriptionLocalizations",
            "attributes": {"name": product["display_name"],
                           "description": product["description"],
                           "locale": self.locale},
            "relationships": {"subscription": {
                "data": {"type": "subscriptions", "id": sub_id}}}}})

    # ── доступность: обязательный шаг перед ценой ──────────────────────────

    def availability(self, sub_id: str) -> list[str]:
        """Страны подписки = страны приложения. Возвращает их коды."""
        rows = self.client.request(
            "GET", f"https://api.appstoreconnect.apple.com/v2/appAvailabilities/"
                   f"{self.app_id}/territoryAvailabilities?limit=200&include=territory")
        codes = [r["relationships"]["territory"]["data"]["id"]
                 for r in rows.get("data", []) if r["attributes"].get("available")]
        if not codes:
            raise Problem("у приложения нет ни одной страны — сначала цена и страны приложения")

        if self.maybe(f"/subscriptions/{sub_id}/subscriptionAvailability"):
            return codes

        self.client.request("POST", "/subscriptionAvailabilities", json={"data": {
            "type": "subscriptionAvailabilities",
            "attributes": {"availableInNewTerritories": True},
            "relationships": {
                "subscription": {"data": {"type": "subscriptions", "id": sub_id}},
                "availableTerritories": {
                    "data": [{"type": "territories", "id": code} for code in codes]},
            }}})
        return codes

    # ── цены ──────────────────────────────────────────────────────────────

    def price_points(self, sub_id: str, price: float) -> list[str]:
        """Базовая точка в USA плюс её пересчёт на остальные страны."""
        points = self.client.get_all(
            f"/subscriptions/{sub_id}/pricePoints?filter[territory]=USA&limit=200")
        base = None
        for point in points:
            if abs(float(point["attributes"]["customerPrice"]) - price) < 0.0001:
                base = point
                break
        if base is None:
            near = sorted({float(p["attributes"]["customerPrice"]) for p in points},
                          key=lambda x: abs(x - price))[:6]
            raise Problem(f"нет ценовой точки {price}; ближайшие: {sorted(near)}")

        equalized = self.client.get_all(
            f"/subscriptionPricePoints/{base['id']}/equalizations?limit=200")
        return [base["id"]] + [p["id"] for p in equalized]

    def set_prices(self, sub_id: str, price: float) -> int:
        have = {
            row["relationships"]["territory"]["data"]["id"]
            for row in self.client.request(
                "GET", f"/subscriptions/{sub_id}/prices?limit=200&include=territory"
            ).get("data", [])
        }
        wanted = self.price_points(sub_id, price)
        if have and len(have) >= len(wanted):
            return len(have)

        def put(point_id: str) -> None:
            self.client.request("POST", "/subscriptionPrices", json={"data": {
                "type": "subscriptionPrices",
                "attributes": {"startDate": None, "preserveCurrentPrice": False},
                "relationships": {
                    "subscription": {"data": {"type": "subscriptions", "id": sub_id}},
                    "subscriptionPricePoint": {
                        "data": {"type": "subscriptionPricePoints", "id": point_id}},
                }}})

        # Территории, где цена уже есть, ASC второй раз не принимает, поэтому
        # ставим только недостающие — иначе повторный прогон падает пачкой 409.
        todo = [pid for pid in wanted if territory_of(pid) not in have]
        with ThreadPoolExecutor(max_workers=PRICE_WORKERS) as pool:
            list(pool.map(put, todo))
        return len(have) + len(todo)

    # ── скриншот для ревью ────────────────────────────────────────────────

    def screenshot(self, sub_id: str, product_id: str) -> bool:
        existing = self.maybe(f"/subscriptions/{sub_id}/appStoreReviewScreenshot")
        if existing and existing.get("data"):
            return True
        if self.shots is None:
            return False

        # Имя файла = product id: у кадра нет локалей, и привязать его к
        # тарифу больше нечем. Это же правило написано ПМу в консоли.
        found = [p for p in sorted(self.shots.iterdir())
                 if p.is_file() and p.stem == product_id]
        if not found:
            raise Problem(
                f"в архиве подписок нет кадра для «{product_id}» — имя файла должно "
                f"быть ровно product id, нашлось: {[p.name for p in self.shots.iterdir()]}")

        image = found[0]
        data = image.read_bytes()
        reserved = self.client.request(
            "POST", "/subscriptionAppStoreReviewScreenshots", json={"data": {
                "type": "subscriptionAppStoreReviewScreenshots",
                "attributes": {"fileName": image.name, "fileSize": len(data)},
                "relationships": {"subscription": {
                    "data": {"type": "subscriptions", "id": sub_id}}}}})
        shot_id = reserved["data"]["id"]
        for operation in reserved["data"]["attributes"]["uploadOperations"]:
            self.client.upload_operation(operation, image)
        self.client.request(
            "PATCH", f"/subscriptionAppStoreReviewScreenshots/{shot_id}", json={"data": {
                "type": "subscriptionAppStoreReviewScreenshots", "id": shot_id,
                "attributes": {"uploaded": True,
                               "sourceFileChecksum": hashlib.md5(data).hexdigest()}}})
        return True

    # ── один продукт целиком ──────────────────────────────────────────────

    def apply(self, group_id: str, product: dict, notes: str | None) -> str:
        sub_id = self.product(group_id, product, notes)
        self.localization(sub_id, product)
        codes = self.availability(sub_id)
        placed = self.set_prices(sub_id, product["price"])
        shot = self.screenshot(sub_id, product["product_id"])
        print(f"    страны: {len(codes)}, цены: {placed}, кадр для ревью: "
              f"{'есть' if shot else 'НЕТ'}")
        return sub_id

    def state(self, sub_id: str) -> str:
        payload = self.client.request(
            "GET", f"/subscriptions/{sub_id}?fields[subscriptions]=state")
        return payload["data"]["attributes"].get("state", "?")


def territory_of(price_point_id: str) -> str:
    """Код страны из идентификатора ценовой точки."""
    import base64
    import json as _json

    padded = price_point_id + "=" * (-len(price_point_id) % 4)
    return _json.loads(base64.urlsafe_b64decode(padded))["t"]


def products_from(listing: dict) -> tuple[list[dict], list[str]]:
    """Продукты, которые можно заводить, и причины по тем, которые нельзя.

    Продукт заводится только целиком: без цены или без описания он застрянет
    в MISSING_METADATA и всё равно не уйдёт на ревью. Поэтому неполный
    продукт пропускается целиком, а остальные заводятся — одна незакрытая
    строка не должна отменять весь пейволл.
    """
    raw = dig(listing, "subscriptions.products")
    if not isinstance(raw, list) or not raw:
        return [], ["subscriptions.products: нет ни одного продукта"]

    out, skipped = [], []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            skipped.append(f"продукт №{index}: ожидается блок полей")
            continue

        name = value_of(item, "id")[0] or f"№{index}"
        missing = []

        def take(key: str):
            text, why = value_of(item, key)
            if text is None:
                missing.append(f"{key} ({why})")
            return text

        values = {key: take(key) for key in ("id", "display_name", "description", "price")}
        duration = item.get("duration") or take("duration")

        if missing:
            skipped.append(f"продукт {name}: не заполнено — {', '.join(missing)}")
            continue

        try:
            price = float(str(values["price"]).lstrip("$").replace(",", "."))
            period = period_of(duration)
        except (ValueError, Problem) as error:
            skipped.append(f"продукт {name}: {error}")
            continue

        out.append({
            "product_id": values["id"],
            "display_name": values["display_name"],
            "description": values["description"],
            "period": period,
            "price": price,
        })
    return out, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listing", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path,
                        help="папка с кадрами для ревью: имя файла = product id")
    parser.add_argument("--verify", action="store_true", help="только прочитать состояние")
    args = parser.parse_args()

    listing = yaml.safe_load(args.listing.read_text(encoding="utf-8"))
    if not isinstance(listing, dict):
        print(f"ERROR: {args.listing} — не похоже на листинг App Store", file=sys.stderr)
        return 1

    if dig(listing, "subscriptions") is None:
        print("Подписок в листинге нет — шаг пропущен.")
        return 0

    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=Path(require_env("ASC_KEY_PATH")),
    )
    app = find_app(client, require_env("APP_IDENTIFIER"))
    locale = str(dig(listing, "meta.locale") or "en-US")

    shots = args.screenshots if args.screenshots and args.screenshots.is_dir() else None
    setup = Subscriptions(client, app["id"], listing, locale, shots)

    group_name, why = value_of(listing, "subscriptions.group")
    if group_name is None:
        print(f"Группа подписок не закрыта ({why}) — продукты не заводим.")
        return 0
    notes, _ = value_of(listing, "subscriptions.notes")
    products, skipped = products_from(listing)

    if skipped:
        print(f"Пропущено продуктов: {len(skipped)}")
        for line in skipped:
            print(f"  - {line}")
    if not products:
        print("Заводить нечего — ни один продукт не закрыт полностью.")
        return 0

    failures = []
    try:
        group_id = setup.group(group_name)
        setup.group_localization(group_id, group_name)
        print(f"  группа «{group_name}»: {group_id}")

        for product in products:
            print(f"  продукт {product['product_id']} ({product['period']}, "
                  f"{product['price']})")
            try:
                sub_id = (setup.apply(group_id, product, notes) if not args.verify
                          else find_subscription(setup, group_id, product["product_id"]))
            except (Problem, AppStoreConnectError) as error:
                # Один сломанный продукт не отменяет остальные: у каждого свой
                # id, своя цена и свой кадр — общего у них только группа.
                print(f"    НЕ ЗАВЕДЁН: {error}", file=sys.stderr)
                failures.append(f"{product['product_id']}: {str(error)[:80]}")
                continue
            step = Step(product["product_id"], "READY_TO_SUBMIT",
                        lambda _want: None, lambda: setup.state(sub_id))
            got, ok = read_back(step, attempts=1 if args.verify else 4)
            print(f"    состояние: {got}")
            if not ok:
                failures.append(f"{product['product_id']} → {got}")
    except (Problem, AppStoreConnectError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if failures:
        print("ERROR: продукты не готовы к отправке: " + "; ".join(failures), file=sys.stderr)
        print("MISSING_METADATA обычно значит, что нет кадра для ревью или цена "
              "проставлена не на все страны.", file=sys.stderr)
        return 1

    print(f"Подписки готовы: {len(products)} продуктов в состоянии READY_TO_SUBMIT.")
    return 0


def find_subscription(setup: Subscriptions, group_id: str, product_id: str) -> str:
    for existing in setup.client.get_all(
            f"/subscriptionGroups/{group_id}/subscriptions?limit=100"):
        if existing["attributes"].get("productId") == product_id:
            return existing["id"]
    raise Problem(f"продукта «{product_id}» в App Store Connect нет")


if __name__ == "__main__":
    raise SystemExit(main())
