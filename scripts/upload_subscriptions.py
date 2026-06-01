#!/usr/bin/env python3
"""Upload subscription localizations to App Store Connect."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "lib"))
from paths import PREPARED_DIR

PREPARED_SUBSCRIPTION_PATH = PREPARED_DIR / "subscription_localizations.json"

SUBSCRIPTION_LIMITS = {
    "name": 30,
    "description": 45,
}

sys.path.insert(0, str(SCRIPT_DIR))
from prepare_metadata import get_subscription_product_id  # noqa: E402
from upload_screenshots_api import (  # noqa: E402
    AppStoreConnectClient,
    AppStoreConnectError,
    find_app,
    require_env,
)


def looks_like_product_id_key(key: str) -> bool:
    key = (key or "").strip()
    return bool(key) and "." in key and " " not in key


def normalize_prepared_products(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not payload:
        return []

    sample_key = next(iter(payload))
    sample_value = payload[sample_key]
    if isinstance(sample_value, dict) and "name" in sample_value:
        return [{"product_id": "", "locales": payload}]

    if isinstance(sample_value, dict):
        products = []
        for product_id, locales in payload.items():
            if not isinstance(locales, dict):
                raise AppStoreConnectError(
                    f"Invalid subscription payload for product '{product_id}' in {PREPARED_SUBSCRIPTION_PATH}"
                )
            products.append({"product_id": product_id, "locales": locales})
        return products

    raise AppStoreConnectError(f"Invalid subscription payload in {PREPARED_SUBSCRIPTION_PATH}")


def load_prepared_products() -> list[dict[str, Any]]:
    if not PREPARED_SUBSCRIPTION_PATH.is_file():
        return []
    payload = json.loads(PREPARED_SUBSCRIPTION_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AppStoreConnectError(f"Invalid subscription payload in {PREPARED_SUBSCRIPTION_PATH}")
    if not payload:
        return []
    return normalize_prepared_products(payload)


def find_subscription(client: AppStoreConnectClient, app_id: str, product_id: str) -> dict[str, Any]:
    groups = client.get_all(f"/apps/{app_id}/subscriptionGroups")
    if not groups:
        raise AppStoreConnectError("No subscription groups found for this app.")

    matches = []
    for group in groups:
        subscriptions = client.get_all(
            f"/subscriptionGroups/{group['id']}/subscriptions"
            "?fields[subscriptions]=productId,name,state"
        )
        for subscription in subscriptions:
            attributes = subscription.get("attributes", {})
            current_product_id = (attributes.get("productId") or "").strip()
            if product_id and current_product_id != product_id:
                continue
            matches.append(
                {
                    "subscription": subscription,
                    "group_id": group["id"],
                    "product_id": current_product_id,
                }
            )

    if not matches:
        if product_id:
            raise AppStoreConnectError(
                f"No subscription found with product id '{product_id}'."
            )
        raise AppStoreConnectError("No subscriptions found in App Store Connect.")

    if product_id:
        return matches[0]["subscription"]

    if len(matches) == 1:
        return matches[0]["subscription"]

    product_ids = ", ".join(sorted(match["product_id"] for match in matches if match["product_id"]))
    raise AppStoreConnectError(
        "Multiple subscriptions found. Set subscription_product_id in config.yaml. "
        f"Available product ids: {product_ids}"
    )


def list_subscription_localizations(client: AppStoreConnectClient, subscription_id: str) -> dict[str, dict[str, Any]]:
    localizations = client.get_all(
        f"/subscriptions/{subscription_id}/subscriptionLocalizations"
        "?fields[subscriptionLocalizations]=locale,name,description"
    )
    by_locale = {}
    for localization in localizations:
        locale = localization.get("attributes", {}).get("locale")
        if locale:
            by_locale[locale] = localization
    return by_locale


def upsert_subscription_localization(
    client: AppStoreConnectClient,
    subscription_id: str,
    locale: str,
    name: str,
    description: str,
    existing: dict[str, Any] | None,
) -> str:
    attributes = {"name": name, "description": description}
    if existing:
        localization_id = existing["id"]
        client.request(
            "PATCH",
            f"/subscriptionLocalizations/{localization_id}",
            json={
                "data": {
                    "type": "subscriptionLocalizations",
                    "id": localization_id,
                    "attributes": attributes,
                }
            },
        )
        return "updated"

    client.request(
        "POST",
        "/subscriptionLocalizations",
        json={
            "data": {
                "type": "subscriptionLocalizations",
                "attributes": {**attributes, "locale": locale},
                "relationships": {
                    "subscription": {
                        "data": {"type": "subscriptions", "id": subscription_id},
                    }
                },
            }
        },
    )
    return "created"


def validate_row(locale: str, row: dict[str, str]) -> list[str]:
    errors = []
    name = row.get("name", "").strip()
    description = row.get("description", "").strip()
    if not name:
        errors.append(f"{locale} subscription name is empty")
    if len(name) > SUBSCRIPTION_LIMITS["name"]:
        errors.append(
            f"{locale} subscription name is {len(name)} chars; max is {SUBSCRIPTION_LIMITS['name']}"
        )
    if description and len(description) > SUBSCRIPTION_LIMITS["description"]:
        errors.append(
            f"{locale} subscription description is {len(description)} chars; "
            f"max is {SUBSCRIPTION_LIMITS['description']}"
        )
    return errors


def upload_product_localizations(
    client: AppStoreConnectClient,
    app_id: str,
    product_id: str,
    prepared_rows: dict[str, dict[str, str]],
) -> tuple[str, int, int, int, int]:
    subscription = find_subscription(client, app_id, product_id)
    subscription_id = subscription["id"]
    product_label = subscription.get("attributes", {}).get("productId") or product_id or subscription_id
    print(f"Using subscription product id: {product_label}")

    existing_by_locale = list_subscription_localizations(client, subscription_id)
    created = 0
    updated = 0
    skipped = 0

    for locale, row in sorted(prepared_rows.items()):
        name = row.get("name", "").strip()
        description = row.get("description", "").strip()
        existing = existing_by_locale.get(locale)
        if existing:
            existing_name = (existing.get("attributes", {}).get("name") or "").strip()
            existing_description = (existing.get("attributes", {}).get("description") or "").strip()
            if existing_name == name and existing_description == description:
                print(f"Skipping {product_label} {locale}: subscription localization already up to date.")
                skipped += 1
                continue

        action = upsert_subscription_localization(
            client,
            subscription_id,
            locale,
            name,
            description,
            existing,
        )
        if action == "created":
            created += 1
            print(f"Created subscription localization for {product_label} {locale}.")
        else:
            updated += 1
            print(f"Updated subscription localization for {product_label} {locale}.")

    return product_label, len(prepared_rows), created, updated, skipped


def main() -> int:
    sys.path.insert(0, str(SCRIPT_DIR / "lib"))
    from automation_report import merge_section

    prepared_products = load_prepared_products()
    if not prepared_products:
        print("No prepared subscription localizations. Skipping subscription upload.")
        merge_section("subscriptions", {"skipped": True, "reason": "no_prepared_data"})
        return 0

    config_product_id = get_subscription_product_id()
    if config_product_id:
        prepared_products = [
            item
            for item in prepared_products
            if not item["product_id"] or item["product_id"] == config_product_id
        ]
        if not prepared_products:
            print(
                f"No prepared subscription data for product id '{config_product_id}'. "
                "Skipping subscription upload."
            )
            merge_section(
                "subscriptions",
                {"skipped": True, "reason": "no_matching_product", "product_id": config_product_id},
            )
            return 0

    validation_errors = []
    for item in prepared_products:
        product_id = item["product_id"] or config_product_id
        prefix = product_id or "subscription"
        for locale, row in item["locales"].items():
            validation_errors.extend(
                [error.replace(f"{locale} ", f"{prefix}:{locale} ", 1) for error in validate_row(locale, row)]
            )
    if validation_errors:
        for error in validation_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        merge_section("subscriptions", {"status": "failed", "validation_errors": len(validation_errors)})
        return 1

    key_path = Path(require_env("ASC_KEY_PATH"))
    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=key_path,
    )
    app = find_app(client, require_env("APP_IDENTIFIER"))
    app_id = app["id"]

    created = 0
    updated = 0
    skipped = 0
    total = 0
    product_labels = []

    for item in prepared_products:
        product_id = item["product_id"] or config_product_id
        if not product_id and len(prepared_products) > 1:
            raise AppStoreConnectError(
                "Multiple subscriptions in prepared data. Set subscription_product_id in config.yaml "
                "or add product ids on the Subs sheet (Подписка row)."
            )
        label, item_total, item_created, item_updated, item_skipped = upload_product_localizations(
            client,
            app_id,
            product_id,
            item["locales"],
        )
        product_labels.append(label)
        total += item_total
        created += item_created
        updated += item_updated
        skipped += item_skipped

    sys.path.insert(0, str(SCRIPT_DIR / "lib"))
    from automation_report import merge_section

    merge_section(
        "subscriptions",
        {
            "product_id": ", ".join(product_labels),
            "total": total,
            "created": created,
            "updated": updated,
            "unchanged": skipped,
            "uploaded": created + updated,
        },
    )
    print(
        "Subscription localization upload completed: "
        f"{created + updated} / {total} locale(s) "
        f"({created} created, {updated} updated, {skipped} skipped)."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AppStoreConnectError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
