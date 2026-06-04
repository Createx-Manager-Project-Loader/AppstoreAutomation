#!/usr/bin/env python3
from __future__ import annotations

import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Za-z]{2,4})?$")

import jwt
import requests

API_BASE_URL = "https://api.appstoreconnect.apple.com/v1"
RELEASED_VERSION_STATES = {"READY_FOR_SALE"}
DEFAULT_BASE_LOCALE = "en-US"
VERSION_URL_FIELDS = ("support_url", "marketing_url")
LIVE_ATTRIBUTES_META_KEY = "__meta__"


class AppStoreConnectError(RuntimeError):
    pass


class AppStoreConnectClient:
    def __init__(self, key_id: str, issuer_id: str, key_path: Path, timeout: int = 60, max_retries: int = 5) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.token = self.create_token(key_id, issuer_id, key_path)

    @staticmethod
    def create_token(key_id: str, issuer_id: str, key_path: Path) -> str:
        now = int(time.time())
        payload = {
            "iss": issuer_id,
            "iat": now,
            "exp": now + 19 * 60,
            "aud": "appstoreconnect-v1",
        }
        headers = {
            "alg": "ES256",
            "kid": key_id,
            "typ": "JWT",
        }
        return jwt.encode(payload, key_path.read_text(encoding="utf-8"), algorithm="ES256", headers=headers)

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{API_BASE_URL}{path}"
        headers = kwargs.pop("headers", {})
        headers.setdefault("Authorization", f"Bearer {self.token}")
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Accept", "application/json")
        kwargs["headers"] = headers
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as error:
                if attempt == self.max_retries:
                    raise AppStoreConnectError(f"{method} {url} failed: {error}") from error
                self.sleep_before_retry(attempt, None)
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                self.sleep_before_retry(attempt, response)
                continue

            if response.status_code == 204:
                return {}

            if not response.ok:
                raise AppStoreConnectError(f"{method} {url} failed with {response.status_code}: {response.text}")

            return response.json() if response.content else {}

        raise AppStoreConnectError(f"{method} {url} failed after {self.max_retries} attempts")

    def sleep_before_retry(self, attempt: int, response: Optional[requests.Response]) -> None:
        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after and retry_after.isdigit():
            delay = int(retry_after)
        else:
            delay = min(30, (2 ** (attempt - 1)) + random.random())
        time.sleep(delay)

    def get_all(self, path: str) -> list[dict[str, Any]]:
        results = []
        next_path: Optional[str] = path
        while next_path:
            response = self.request("GET", next_path)
            results.extend(response.get("data", []))
            next_path = response.get("links", {}).get("next")
        return results


def version_sort_key(version_string: str) -> list[Any]:
    parts = []
    for part in version_string.strip().split("."):
        try:
            parts.append((0, int(part)))
        except ValueError:
            parts.append((1, part))
    return parts


def _prepared_dir(root_dir: Path) -> Path:
    value = os.environ.get("AUTOMATION_PREPARED_DIR")
    if value:
        return Path(value)
    return root_dir / "automation-prepared"


def asc_config(root_dir: Path) -> Optional[tuple[str, str, Path, str]]:
    key_id = os.environ.get("ASC_KEY_ID") or os.environ.get("APPSTORE_CONNECT_API_KEY_ID")
    issuer_id = os.environ.get("ASC_ISSUER_ID") or os.environ.get("APPSTORE_CONNECT_API_ISSUER_ID")
    bundle_id = os.environ.get("APP_IDENTIFIER") or os.environ.get("BUNDLE_IDENTIFIER")
    private_key = os.environ.get("ASC_PRIVATE_KEY") or os.environ.get("APPSTORE_CONNECT_API_PRIVATE_KEY")
    key_path_value = os.environ.get("ASC_KEY_PATH")

    if not key_id or not issuer_id or not bundle_id:
        return None

    if private_key:
        prepared_dir = _prepared_dir(root_dir)
        key_path = prepared_dir / "secrets" / f"AuthKey_{key_id}.p8"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(private_key.rstrip() + "\n", encoding="utf-8")
        key_path.chmod(0o600)
        return key_id, issuer_id, key_path, bundle_id

    if key_path_value:
        key_path = Path(key_path_value)
        if not key_path.is_absolute():
            key_path = root_dir / key_path
        if key_path.is_file():
            return key_id, issuer_id, key_path, bundle_id

    return None


def find_app(client: AppStoreConnectClient, bundle_id: str) -> dict[str, Any]:
    apps = client.get_all(f"/apps?filter[bundleId]={bundle_id}&fields[apps]=bundleId,name,sku,primaryLocale")
    if not apps:
        raise AppStoreConnectError(f"No App Store Connect app found for bundle id: {bundle_id}")
    if len(apps) > 1:
        raise AppStoreConnectError(f"Expected one app for bundle id {bundle_id}, got {len(apps)}")
    return apps[0]


def find_latest_released_version(client: AppStoreConnectClient, app_id: str) -> Optional[dict[str, Any]]:
    versions = client.get_all(
        f"/apps/{app_id}/appStoreVersions?filter[platform]=IOS"
        "&fields[appStoreVersions]=versionString,appStoreState"
    )
    released_versions = [
        version
        for version in versions
        if version.get("attributes", {}).get("appStoreState") in RELEASED_VERSION_STATES
    ]
    if not released_versions:
        return None

    released_versions.sort(
        key=lambda version: version_sort_key(version.get("attributes", {}).get("versionString", "")),
        reverse=True,
    )
    return released_versions[0]


def fetch_live_version_localization_attributes(root_dir: Path) -> dict[str, dict[str, str]]:
    config = asc_config(root_dir)
    if config is None:
        return {}

    key_id, issuer_id, key_path, bundle_id = config
    client = AppStoreConnectClient(key_id, issuer_id, key_path)

    app = find_app(client, bundle_id)
    primary_locale = (app.get("attributes", {}).get("primaryLocale") or base_locale()).strip()
    version = find_latest_released_version(client, app["id"])
    if version is None:
        return {}

    version_attributes = version.get("attributes", {})
    print(
        "Using version localization fields from released App Store version "
        f"{version_attributes.get('versionString')} ({version_attributes.get('appStoreState')})"
    )

    localizations = client.get_all(
        f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations"
        "?fields[appStoreVersionLocalizations]=locale,description,keywords,whatsNew,supportUrl,marketingUrl"
    )

    attributes_by_locale: dict[str, dict[str, str]] = {
        LIVE_ATTRIBUTES_META_KEY: {"primary_locale": primary_locale}
    }
    for localization in localizations:
        attributes = localization.get("attributes", {})
        locale = attributes.get("locale")
        if not locale:
            continue

        entry: dict[str, str] = {}
        description = (attributes.get("description") or "").strip()
        if description:
            entry["description"] = description

        keywords = (attributes.get("keywords") or "").strip()
        if keywords:
            entry["keywords"] = keywords

        whats_new = (attributes.get("whatsNew") or "").strip()
        if whats_new:
            entry["whats_new"] = whats_new

        support_url = (attributes.get("supportUrl") or "").strip()
        if support_url:
            entry["support_url"] = support_url

        marketing_url = (attributes.get("marketingUrl") or "").strip()
        if marketing_url:
            entry["marketing_url"] = marketing_url

        if entry:
            attributes_by_locale[locale] = entry

    return attributes_by_locale


def fetch_live_release_notes_by_locale(root_dir: Path) -> dict[str, str]:
    attributes_by_locale = fetch_live_version_localization_attributes(root_dir)
    return {
        locale: attributes["whats_new"]
        for locale, attributes in attributes_by_locale.items()
        if attributes.get("whats_new")
    }


def fetch_editable_release_note_locales(root_dir: Path) -> list[str]:
    config = asc_config(root_dir)
    if config is None:
        return []

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from upload_screenshots_api import find_editable_version

    key_id, issuer_id, key_path, bundle_id = config
    client = AppStoreConnectClient(key_id, issuer_id, key_path)

    app = find_app(client, bundle_id)
    version = find_editable_version(client, app["id"])
    version_attributes = version.get("attributes", {})
    print(
        "Using locales from editable App Store version "
        f"{version_attributes.get('versionString')} ({version_attributes.get('appStoreState')})"
    )

    localizations = client.get_all(
        f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations"
        "?fields[appStoreVersionLocalizations]=locale"
    )

    locales = []
    for localization in localizations:
        locale = localization.get("attributes", {}).get("locale")
        if locale and LOCALE_RE.match(locale):
            locales.append(locale)

    return sorted(set(locales))


def fetch_live_release_note_locales(root_dir: Path) -> list[str]:
    config = asc_config(root_dir)
    if config is None:
        return []

    key_id, issuer_id, key_path, bundle_id = config
    client = AppStoreConnectClient(key_id, issuer_id, key_path)

    app = find_app(client, bundle_id)
    version = find_latest_released_version(client, app["id"])
    if version is None:
        return []

    localizations = client.get_all(
        f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations"
        "?fields[appStoreVersionLocalizations]=locale"
    )

    locales = []
    for localization in localizations:
        locale = localization.get("attributes", {}).get("locale")
        if locale and LOCALE_RE.match(locale):
            locales.append(locale)

    return sorted(set(locales))


def read_fallback_release_notes(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def base_locale() -> str:
    return (os.environ.get("RELEASE_NOTES_BASE_LOCALE") or DEFAULT_BASE_LOCALE).strip()


def primary_locale_from_live(live_attributes: Optional[dict[str, dict[str, str]]]) -> str:
    if live_attributes:
        primary = live_attributes.get(LIVE_ATTRIBUTES_META_KEY, {}).get("primary_locale", "").strip()
        if primary:
            return primary
    return base_locale()


def primary_fields_from_live(live_attributes: Optional[dict[str, dict[str, str]]]) -> dict[str, str]:
    if not live_attributes:
        return {}
    primary_locale = primary_locale_from_live(live_attributes)
    return dict(live_attributes.get(primary_locale, {}))


def resolve_release_notes_for_locales(
    locales: list[str],
    root_dir: Path,
    fallback: str | Path = "",
    live_attributes: Optional[dict[str, dict[str, str]]] = None,
) -> tuple[dict[str, str], dict[str, int]]:
    from prepare_metadata import release_notes_fallback_source

    if isinstance(fallback, Path):
        fallback_text = read_fallback_release_notes(fallback)
    else:
        fallback_text = (fallback or "").strip()

    live_notes: dict[str, str] = {}
    base = base_locale()

    try:
        if live_attributes is None:
            live_attributes = fetch_live_version_localization_attributes(root_dir)
        live_notes = {
            locale: attributes["whats_new"]
            for locale, attributes in live_attributes.items()
            if attributes.get("whats_new")
        }
    except AppStoreConnectError as error:
        print(f"WARNING: Could not fetch live What's New from App Store Connect: {error}", file=sys.stderr)
    except requests.RequestException as error:
        print(f"WARNING: Could not fetch live What's New from App Store Connect: {error}", file=sys.stderr)

    primary = primary_locale_from_live(live_attributes)
    primary_live_text = live_notes.get(primary, "").strip() if live_notes else ""
    base_live_text = live_notes.get(base, "").strip() if live_notes and base != primary else ""

    resolved = {}
    live_locales = []
    primary_locales = []
    base_locales = []
    file_locales = []
    stats = {"source_live": 0, "source_primary": 0, "source_base": 0, "source_config": 0}

    for locale in locales:
        live_text = live_notes.get(locale, "").strip()
        if live_text:
            resolved[locale] = live_text
            live_locales.append(locale)
        elif primary_live_text:
            resolved[locale] = primary_live_text
            primary_locales.append(locale)
        elif base_live_text:
            resolved[locale] = base_live_text
            base_locales.append(locale)
        elif fallback_text:
            resolved[locale] = fallback_text
            file_locales.append(locale)

    stats["source_live"] = len(live_locales)
    stats["source_primary"] = len(primary_locales)
    stats["source_base"] = len(base_locales)
    stats["source_config"] = len(file_locales)

    if live_locales:
        print("Prepared What's New from live App Store version for: " + ", ".join(sorted(live_locales)))
    if primary_locales:
        print(
            f"Prepared What's New from primary locale {primary} in live App Store version for: "
            + ", ".join(sorted(primary_locales))
        )
    if base_locales:
        print(
            f"Prepared What's New from base locale {base} in live App Store version for: "
            + ", ".join(sorted(base_locales))
        )
    if file_locales:
        fallback_label = (
            "workflow release_notes"
            if release_notes_fallback_source() == "workflow_or_env"
            else "config release_notes"
        )
        print(f"Prepared What's New from {fallback_label} for: " + ", ".join(sorted(file_locales)))
    elif fallback_text and resolved and not live_locales and not primary_locales and not base_locales:
        fallback_label = (
            "workflow release_notes"
            if release_notes_fallback_source() == "workflow_or_env"
            else "config release_notes"
        )
        print(f"Prepared What's New from {fallback_label} for all locales.")

    return resolved, stats


def resolve_descriptions_for_locales(
    locales: list[str],
    description_rows: dict[str, dict[str, str]],
    root_dir: Path,
    live_attributes: Optional[dict[str, dict[str, str]]] = None,
) -> tuple[dict[str, str], dict[str, int]]:
    """Prefer Description sheet text; otherwise the same locale in the latest released version."""
    live_descriptions: dict[str, str] = {}

    try:
        if live_attributes is None:
            live_attributes = fetch_live_version_localization_attributes(root_dir)
        live_descriptions = {
            locale: attributes["description"]
            for locale, attributes in live_attributes.items()
            if locale != LIVE_ATTRIBUTES_META_KEY and attributes.get("description")
        }
    except AppStoreConnectError as error:
        print(f"WARNING: Could not fetch live descriptions from App Store Connect: {error}", file=sys.stderr)
    except requests.RequestException as error:
        print(f"WARNING: Could not fetch live descriptions from App Store Connect: {error}", file=sys.stderr)

    resolved: dict[str, str] = {}
    file_locales: list[str] = []
    live_locales: list[str] = []
    stats = {"source_file": 0, "source_live": 0}

    for locale in locales:
        file_text = description_rows.get(locale, {}).get("description", "").strip()
        if file_text:
            resolved[locale] = file_text
            file_locales.append(locale)
            continue

        live_text = live_descriptions.get(locale, "").strip()
        if live_text:
            resolved[locale] = live_text
            live_locales.append(locale)

    stats["source_file"] = len(file_locales)
    stats["source_live"] = len(live_locales)

    if file_locales:
        print("Prepared description from Google Sheet for: " + ", ".join(sorted(file_locales)))
    if live_locales:
        print(
            "Prepared description from released App Store version for: "
            + ", ".join(sorted(live_locales))
        )

    return resolved, stats


def resolve_keywords_for_locales(
    locales: list[str],
    aso_rows: dict[str, dict[str, str]],
    root_dir: Path,
    live_attributes: Optional[dict[str, dict[str, str]]] = None,
) -> tuple[dict[str, str], dict[str, int]]:
    """ASO sheet keywords first; for locales missing from ASO use released locale, then primary."""
    try:
        if live_attributes is None:
            live_attributes = fetch_live_version_localization_attributes(root_dir)
    except AppStoreConnectError as error:
        print(f"WARNING: Could not fetch live keywords from App Store Connect: {error}", file=sys.stderr)
        live_attributes = live_attributes or {}
    except requests.RequestException as error:
        print(f"WARNING: Could not fetch live keywords from App Store Connect: {error}", file=sys.stderr)
        live_attributes = live_attributes or {}

    primary_keywords = primary_fields_from_live(live_attributes).get("keywords", "").strip()
    primary = primary_locale_from_live(live_attributes)

    resolved: dict[str, str] = {}
    file_locales: list[str] = []
    live_locales: list[str] = []
    primary_locales: list[str] = []
    stats = {"source_file": 0, "source_live": 0, "source_primary": 0}

    for locale in locales:
        if locale in aso_rows:
            sheet_text = aso_rows[locale].get("keywords", "").strip()
            if sheet_text:
                resolved[locale] = sheet_text
                file_locales.append(locale)
                continue

        if locale in aso_rows:
            continue

        live_text = ""
        if live_attributes:
            live_text = live_attributes.get(locale, {}).get("keywords", "").strip()
        if live_text:
            resolved[locale] = live_text
            live_locales.append(locale)
            continue

        if primary_keywords:
            resolved[locale] = primary_keywords
            primary_locales.append(locale)

    stats["source_file"] = len(file_locales)
    stats["source_live"] = len(live_locales)
    stats["source_primary"] = len(primary_locales)

    if file_locales:
        print("Prepared keywords from Google Sheet ASO for: " + ", ".join(sorted(file_locales)))
    if live_locales:
        print(
            "Prepared keywords from released App Store version for locales missing from ASO: "
            + ", ".join(sorted(live_locales))
        )
    if primary_locales:
        print(
            f"Prepared keywords from primary locale {primary} for locales missing from ASO: "
            + ", ".join(sorted(primary_locales))
        )

    return resolved, stats


def resolve_version_urls_for_locales(
    locales: list[str],
    root_dir: Path,
    live_attributes: Optional[dict[str, dict[str, str]]] = None,
) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    stats = {"urls_source_primary": 0, "urls_source_fallback": 0}

    try:
        if live_attributes is None:
            live_attributes = fetch_live_version_localization_attributes(root_dir)
    except AppStoreConnectError as error:
        print(f"WARNING: Could not fetch live Support/Marketing URLs from App Store Connect: {error}", file=sys.stderr)
        return {}, stats
    except requests.RequestException as error:
        print(f"WARNING: Could not fetch live Support/Marketing URLs from App Store Connect: {error}", file=sys.stderr)
        return {}, stats

    if not live_attributes:
        return {}, stats

    source_locale = (
        os.environ.get("VERSION_URL_SOURCE_LOCALE")
        or live_attributes.get(LIVE_ATTRIBUTES_META_KEY, {}).get("primary_locale")
        or base_locale()
    ).strip()
    source_entry = live_attributes.get(source_locale, {})
    source_kind = "primary"

    if not any(source_entry.get(field, "").strip() for field in VERSION_URL_FIELDS):
        fallback_locale = next(
            (
                locale
                for locale, attributes in sorted(live_attributes.items())
                if locale != LIVE_ATTRIBUTES_META_KEY
                and any(attributes.get(field, "").strip() for field in VERSION_URL_FIELDS)
            ),
            "",
        )
        if fallback_locale:
            print(
                f"WARNING: No Support/Marketing URLs found in primary locale {source_locale}; "
                f"using {fallback_locale} from the released version instead.",
                file=sys.stderr,
            )
            source_locale = fallback_locale
            source_entry = live_attributes[source_locale]
            source_kind = "fallback"

    if not any(source_entry.get(field, "").strip() for field in VERSION_URL_FIELDS):
        return {}, stats

    resolved: dict[str, dict[str, str]] = {}

    for locale in locales:
        locale_urls: dict[str, str] = {}

        for field in VERSION_URL_FIELDS:
            value = source_entry.get(field, "").strip()
            if value:
                locale_urls[field] = value

        if not locale_urls:
            continue

        resolved[locale] = locale_urls

    if source_kind == "primary":
        stats["urls_source_primary"] = len(resolved)
    else:
        stats["urls_source_fallback"] = len(resolved)

    print(
        f"Prepared Support/Marketing URLs from released version locale {source_locale} "
        f"for {len(resolved)} locale(s)."
    )

    return resolved, stats


def apply_version_urls_to_metadata_dir(
    metadata_dir: Path,
    root_dir: Path,
    locales: Optional[list[str]] = None,
    live_attributes: Optional[dict[str, dict[str, str]]] = None,
) -> tuple[int, dict[str, int]]:
    if locales is None:
        locales = sorted(path.name for path in metadata_dir.iterdir() if path.is_dir() and LOCALE_RE.match(path.name))
    if not locales:
        return 0, {}

    resolved, stats = resolve_version_urls_for_locales(locales, root_dir, live_attributes=live_attributes)
    if not resolved:
        return 0, stats

    updated = 0
    for locale, urls in resolved.items():
        for field, value in urls.items():
            target = metadata_dir / locale / f"{field}.txt"
            if target.is_file() and target.read_text(encoding="utf-8").strip():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value.rstrip() + "\n", encoding="utf-8")
            updated += 1

    return updated, stats


def apply_release_notes_to_metadata_dir(metadata_dir: Path, root_dir: Path, fallback: str | Path = "") -> tuple[int, dict[str, int]]:
    locales = sorted(path.name for path in metadata_dir.iterdir() if path.is_dir() and LOCALE_RE.match(path.name))
    if not locales:
        return 0, {}

    live_attributes: Optional[dict[str, dict[str, str]]] = None
    try:
        live_attributes = fetch_live_version_localization_attributes(root_dir)
    except (AppStoreConnectError, requests.RequestException) as error:
        print(f"WARNING: Could not fetch live version localizations from App Store Connect: {error}", file=sys.stderr)

    resolved, stats = resolve_release_notes_for_locales(
        locales,
        root_dir,
        fallback,
        live_attributes=live_attributes,
    )
    if not resolved:
        url_files, url_stats = apply_version_urls_to_metadata_dir(
            metadata_dir,
            root_dir,
            locales,
            live_attributes=live_attributes,
        )
        stats.update(url_stats)
        stats["urls_prepared"] = url_files
        return 0, stats

    updated = 0
    for locale, text in resolved.items():
        target = metadata_dir / locale / "release_notes.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text.rstrip() + "\n", encoding="utf-8")
        updated += 1

    url_files, url_stats = apply_version_urls_to_metadata_dir(
        metadata_dir,
        root_dir,
        locales,
        live_attributes=live_attributes,
    )
    stats.update(url_stats)
    stats["urls_prepared"] = url_files
    return updated, stats


def record_whats_new_prepare(updated: int, total_locales: int, stats: dict[str, int]) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from automation_report import merge_section

    payload = {
        "locales_total": total_locales,
        "release_notes_prepared": updated,
    }
    payload.update(stats)
    merge_section("whats_new", payload)


def main() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from prepare_metadata import REPO_ROOT, get_release_notes_fallback

    metadata_dir = Path(os.environ.get("METADATA_DIR", str(REPO_ROOT / "metadata")))
    fallback = get_release_notes_fallback()

    locales = sorted(path.name for path in metadata_dir.iterdir() if path.is_dir() and LOCALE_RE.match(path.name))
    updated, stats = apply_release_notes_to_metadata_dir(metadata_dir, REPO_ROOT, fallback)
    if updated == 0 and not stats.get("urls_prepared"):
        print(f"ERROR: No release notes or Support/Marketing URLs prepared in {metadata_dir}", file=sys.stderr)
        raise SystemExit(1)

    from prepare_metadata import release_notes_fallback_source

    record_whats_new_prepare(updated, len(locales), stats)
    if release_notes_fallback_source() == "workflow_or_env":
        print(
            "What's New fallback source: workflow_dispatch / RELEASE_NOTES env "
            "(replaces config.yaml; live App Store text still takes priority per locale)."
        )
    if stats.get("urls_prepared"):
        print(f"Done. Updated Support/Marketing URL file(s) for {stats['urls_prepared']} field(s).")
    if updated:
        print(f"Done. Updated release_notes.txt for {updated} locale(s).")


if __name__ == "__main__":
    main()
