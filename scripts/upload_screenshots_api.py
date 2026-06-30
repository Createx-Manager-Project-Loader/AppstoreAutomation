#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import random
import struct
import sys
import time
from pathlib import Path
from typing import Any, Optional

import jwt
import requests


API_BASE_URL = "https://api.appstoreconnect.apple.com/v1"
EDITABLE_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "DEVELOPER_REJECTED",
    "REJECTED",
    "METADATA_REJECTED",
    "WAITING_FOR_REVIEW",
    "INVALID_BINARY",
}
STATE_PRIORITY = [
    "PREPARE_FOR_SUBMISSION",
    "DEVELOPER_REJECTED",
    "REJECTED",
    "METADATA_REJECTED",
    "WAITING_FOR_REVIEW",
    "INVALID_BINARY",
]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
DISPLAY_TYPES_BY_SIZE = {
    # iPhone
    (1290, 2796): "APP_IPHONE_67",
    (2796, 1290): "APP_IPHONE_67",
    (1320, 2868): "APP_IPHONE_67",
    (2868, 1320): "APP_IPHONE_67",
    (1242, 2688): "APP_IPHONE_65",
    (2688, 1242): "APP_IPHONE_65",
    (1284, 2778): "APP_IPHONE_65",
    (2778, 1284): "APP_IPHONE_65",
    (1170, 2532): "APP_IPHONE_61",
    (2532, 1170): "APP_IPHONE_61",
    (1179, 2556): "APP_IPHONE_61",
    (2556, 1179): "APP_IPHONE_61",
    (1125, 2436): "APP_IPHONE_58",
    (2436, 1125): "APP_IPHONE_58",
    (1242, 2208): "APP_IPHONE_55",
    (2208, 1242): "APP_IPHONE_55",
    (750, 1334): "APP_IPHONE_47",
    (1334, 750): "APP_IPHONE_47",
    (640, 1136): "APP_IPHONE_40",
    (1136, 640): "APP_IPHONE_40",
    # iPad
    (2048, 2732): "APP_IPAD_PRO_3GEN_129",
    (2732, 2048): "APP_IPAD_PRO_3GEN_129",
    (2064, 2752): "APP_IPAD_PRO_3GEN_129",
    (2752, 2064): "APP_IPAD_PRO_3GEN_129",
    (1668, 2388): "APP_IPAD_PRO_3GEN_11",
    (2388, 1668): "APP_IPAD_PRO_3GEN_11",
    (1640, 2360): "APP_IPAD_PRO_3GEN_11",
    (2360, 1640): "APP_IPAD_PRO_3GEN_11",
    (1536, 2048): "APP_IPAD_PRO_129",
    (2048, 1536): "APP_IPAD_PRO_129",
}


class AppStoreConnectError(RuntimeError):
    pass


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise SystemExit(f"{name} must be an integer") from error


def image_sort_key(path: Path) -> tuple[int, str]:
    digits = "".join(character for character in path.stem if character.isdigit())
    return (int(digits) if digits else 9999, path.name.lower())


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as file:
        header = file.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    return struct.unpack(">II", header[16:24])


def jpeg_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as file:
        if file.read(2) != b"\xff\xd8":
            raise ValueError("not a JPEG file")
        while True:
            marker_prefix = file.read(1)
            if not marker_prefix:
                break
            if marker_prefix != b"\xff":
                continue
            marker = file.read(1)
            while marker == b"\xff":
                marker = file.read(1)
            if marker in {b"\xd8", b"\xd9"}:
                continue
            length_bytes = file.read(2)
            if len(length_bytes) != 2:
                break
            length = struct.unpack(">H", length_bytes)[0]
            if marker and 0xC0 <= marker[0] <= 0xCF and marker not in {b"\xc4", b"\xc8", b"\xcc"}:
                data = file.read(length - 2)
                if len(data) < 5:
                    break
                height, width = struct.unpack(">HH", data[1:5])
                return width, height
            file.seek(length - 2, os.SEEK_CUR)
    raise ValueError("could not read JPEG dimensions")


def image_dimensions(path: Path) -> tuple[int, int]:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return png_dimensions(path)
    if suffix in {".jpg", ".jpeg"}:
        return jpeg_dimensions(path)
    raise ValueError(f"Unsupported image extension: {path.suffix}")


def display_type_for_image(path: Path) -> str:
    dimensions = image_dimensions(path)
    try:
        return DISPLAY_TYPES_BY_SIZE[dimensions]
    except KeyError as error:
        raise AppStoreConnectError(
            f"Unsupported screenshot size for {path}: {dimensions[0]}x{dimensions[1]}. "
            "Add this size to DISPLAY_TYPES_BY_SIZE before uploading."
        ) from error


def md5_hex(path: Path) -> str:
    digest = hashlib.md5()  # nosec: Apple requires MD5 for sourceFileChecksum.
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AppStoreConnectClient:
    def __init__(
        self,
        key_id: str,
        issuer_id: str,
        key_path: Path,
        timeout: int = 60,
        max_retries: int = 5,
    ) -> None:
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
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        from log import log_api_request, log_api_response, log_info

        url = path if path.startswith("http") else f"{API_BASE_URL}{path}"
        headers = kwargs.pop("headers", {})
        headers.setdefault("Authorization", f"Bearer {self.token}")
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Accept", "application/json")
        kwargs["headers"] = headers
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(1, self.max_retries + 1):
            log_api_request(method, url)
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as error:
                log_api_response(method, url, 0, str(error))
                if attempt == self.max_retries:
                    raise AppStoreConnectError(f"{method} {url} failed: {error}") from error
                self.sleep_before_retry(attempt, None)
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                log_api_response(method, url, response.status_code, response.text)
                self.sleep_before_retry(attempt, response)
                continue

            if response.status_code == 204:
                log_api_response(method, url, response.status_code)
                return {}

            if not response.ok:
                log_api_response(method, url, response.status_code, response.text)
                raise AppStoreConnectError(f"{method} {url} failed with {response.status_code}: {response.text}")

            log_api_response(method, url, response.status_code)
            if method == "GET":
                payload = response.json() if response.content else {}
                data = payload.get("data", [])
                if isinstance(data, list):
                    log_info(f"ASC API {method} {url} returned {len(data)} item(s)")
                return payload

            return response.json() if response.content else {}

        raise AppStoreConnectError(f"{method} {url} failed after {self.max_retries} attempts")

    def sleep_before_retry(self, attempt: int, response: Optional[requests.Response]) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        from log import log_warn

        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after and retry_after.isdigit():
            delay = int(retry_after)
        else:
            delay = min(30, (2 ** (attempt - 1)) + random.random())
        log_warn(f"Retrying App Store Connect request after {delay:.1f} second(s)...")
        time.sleep(delay)

    def get_all(self, path: str) -> list[dict[str, Any]]:
        results = []
        next_path: Optional[str] = path
        while next_path:
            response = self.request("GET", next_path)
            results.extend(response.get("data", []))
            next_path = response.get("links", {}).get("next")
        return results

    def upload_operation(self, operation: dict[str, Any], image_path: Path) -> None:
        method = operation.get("method", "PUT")
        url = operation["url"]
        offset = int(operation.get("offset", 0))
        length = int(operation.get("length", image_path.stat().st_size))
        headers = {header["name"]: header["value"] for header in operation.get("requestHeaders", [])}

        with image_path.open("rb") as file:
            file.seek(offset)
            data = file.read(length)

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.request(method, url, headers=headers, data=data, timeout=self.timeout)
            except requests.RequestException as error:
                if attempt == self.max_retries:
                    raise AppStoreConnectError(f"Upload failed for {image_path}: {error}") from error
                self.sleep_before_retry(attempt, None)
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                self.sleep_before_retry(attempt, response)
                continue

            if not response.ok:
                raise AppStoreConnectError(
                    f"Upload failed for {image_path} with {response.status_code}: {response.text}"
                )
            return

        raise AppStoreConnectError(f"Upload failed for {image_path} after {self.max_retries} attempts")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def find_app(client: AppStoreConnectClient, bundle_id: str) -> dict[str, Any]:
    apps = client.get_all(f"/apps?filter[bundleId]={bundle_id}&fields[apps]=bundleId,name,sku")
    if not apps:
        raise AppStoreConnectError(f"No App Store Connect app found for bundle id: {bundle_id}")
    if len(apps) > 1:
        raise AppStoreConnectError(f"Expected one app for bundle id {bundle_id}, got {len(apps)}")
    return apps[0]


def version_sort_key(version_string: str) -> list[Any]:
    parts = []
    for part in version_string.strip().split("."):
        try:
            parts.append((0, int(part)))
        except ValueError:
            parts.append((1, part))
    return parts


def list_ios_app_store_versions(client: AppStoreConnectClient, app_id: str) -> list[dict[str, Any]]:
    requested_version = os.environ.get("ASC_APP_STORE_VERSION") or os.environ.get("APP_STORE_VERSION")
    path = (
        f"/apps/{app_id}/appStoreVersions?filter[platform]=IOS"
        "&fields[appStoreVersions]=platform,versionString,appStoreState"
    )
    if requested_version:
        path += f"&filter[versionString]={requested_version}"
    return client.get_all(path)


def bump_minor_version_string(version_string: str) -> str:
    version_string = version_string.strip()
    if not version_string:
        raise AppStoreConnectError("Empty version string")
    parts = version_string.split(".")
    if not all(part.isdigit() for part in parts):
        raise AppStoreConnectError(f"Cannot auto-bump non-numeric version '{version_string}'")
    if len(parts) == 1:
        return f"{parts[0]}.1"
    minor_index = 1
    parts[minor_index] = str(int(parts[minor_index]) + 1)
    for index in range(minor_index + 1, len(parts)):
        parts[index] = "0"
    return ".".join(parts)


def choose_next_version_string(existing_versions: list[dict[str, Any]]) -> str:
    version_strings = [
        str(version.get("attributes", {}).get("versionString", "")).strip()
        for version in existing_versions
    ]
    version_strings = [value for value in version_strings if value]
    if not version_strings:
        return "1.0"

    latest = max(version_strings, key=version_sort_key)
    used = set(version_strings)
    candidate = bump_minor_version_string(latest)
    for _ in range(50):
        if candidate not in used:
            return candidate
        candidate = bump_minor_version_string(candidate)
    raise AppStoreConnectError(f"Could not find unused version string after '{latest}'")


def create_app_store_version(client: AppStoreConnectClient, app_id: str, version_string: str) -> dict[str, Any]:
    response = client.request(
        "POST",
        "/appStoreVersions",
        json={
            "data": {
                "type": "appStoreVersions",
                "attributes": {
                    "platform": "IOS",
                    "versionString": version_string,
                },
                "relationships": {
                    "app": {
                        "data": {
                            "type": "apps",
                            "id": app_id,
                        }
                    }
                },
            }
        },
    )
    return response["data"]


def list_version_localization_locales(client: AppStoreConnectClient, version_id: str) -> list[str]:
    localizations = client.get_all(
        f"/appStoreVersions/{version_id}/appStoreVersionLocalizations"
        "?fields[appStoreVersionLocalizations]=locale"
    )
    locales = []
    for localization in localizations:
        locale = str(localization.get("attributes", {}).get("locale", "")).strip()
        if locale:
            locales.append(locale)
    return locales


def create_version_localization(client: AppStoreConnectClient, version_id: str, locale: str) -> dict[str, Any]:
    response = client.request(
        "POST",
        "/appStoreVersionLocalizations",
        json={
            "data": {
                "type": "appStoreVersionLocalizations",
                "attributes": {"locale": locale},
                "relationships": {
                    "appStoreVersion": {
                        "data": {
                            "type": "appStoreVersions",
                            "id": version_id,
                        }
                    }
                },
            }
        },
    )
    return response["data"]


def seed_version_localizations(
    client: AppStoreConnectClient,
    source_version_id: str,
    target_version_id: str,
) -> int:
    source_locales = list_version_localization_locales(client, source_version_id)
    target_locales = set(list_version_localization_locales(client, target_version_id))
    created = 0
    for locale in source_locales:
        if locale in target_locales:
            continue
        create_version_localization(client, target_version_id, locale)
        target_locales.add(locale)
        created += 1
    return created


def find_best_seed_version(existing_versions: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not existing_versions:
        return None
    released = [
        version
        for version in existing_versions
        if version.get("attributes", {}).get("appStoreState") == "READY_FOR_SALE"
    ]
    pool = released if released else existing_versions
    return max(
        pool,
        key=lambda version: version_sort_key(str(version.get("attributes", {}).get("versionString", ""))),
    )


def ensure_editable_app_store_version(client: AppStoreConnectClient, app_id: str, *, auto_create: bool = True) -> dict[str, Any]:
    try:
        return find_editable_version(client, app_id)
    except AppStoreConnectError as error:
        if not auto_create or "No editable iOS app store version found" not in str(error):
            raise

    existing_versions = list_ios_app_store_versions(client, app_id)
    next_version_string = choose_next_version_string(existing_versions)
    print(
        "No editable App Store version found. "
        f"Creating iOS version {next_version_string}..."
    )
    created_version = create_app_store_version(client, app_id, next_version_string)
    created_version_id = created_version["id"]

    seed_version = find_best_seed_version(existing_versions)
    if seed_version:
        seed_attrs = seed_version.get("attributes", {})
        seeded_count = seed_version_localizations(client, seed_version["id"], created_version_id)
        print(
            "Seeded "
            f"{seeded_count} localization(s) from version "
            f"{seed_attrs.get('versionString')} ({seed_attrs.get('appStoreState')})."
        )

    return find_editable_version(client, app_id)


def find_editable_version(client: AppStoreConnectClient, app_id: str) -> dict[str, Any]:
    versions = list_ios_app_store_versions(client, app_id)
    editable_versions = [
        version for version in versions if version.get("attributes", {}).get("appStoreState") in EDITABLE_STATES
    ]
    if not editable_versions:
        states = ", ".join(
            f"{version.get('attributes', {}).get('versionString')}:{version.get('attributes', {}).get('appStoreState')}"
            for version in versions
        )
        raise AppStoreConnectError(f"No editable iOS app store version found. Seen versions: {states or 'none'}")

    editable_versions.sort(
        key=lambda version: STATE_PRIORITY.index(version.get("attributes", {}).get("appStoreState"))
        if version.get("attributes", {}).get("appStoreState") in STATE_PRIORITY
        else len(STATE_PRIORITY)
    )
    return editable_versions[0]


def find_or_create_localization(client: AppStoreConnectClient, version_id: str, locale: str, dry_run: bool) -> dict[str, Any]:
    localizations = client.get_all(
        f"/appStoreVersions/{version_id}/appStoreVersionLocalizations"
        "?fields[appStoreVersionLocalizations]=locale"
    )
    for localization in localizations:
        if localization.get("attributes", {}).get("locale") == locale:
            return localization

    if dry_run:
        print(f"DRY RUN: would create localization {locale}")
        return {"id": "dry-run-localization", "attributes": {"locale": locale}}

    print(f"Creating localization {locale}...")
    return client.request(
        "POST",
        "/appStoreVersionLocalizations",
        json={
            "data": {
                "type": "appStoreVersionLocalizations",
                "attributes": {"locale": locale},
                "relationships": {
                    "appStoreVersion": {
                        "data": {"type": "appStoreVersions", "id": version_id},
                    }
                },
            }
        },
    )["data"]


def list_screenshot_sets(client: AppStoreConnectClient, localization_id: str) -> list[dict[str, Any]]:
    return client.get_all(
        f"/appStoreVersionLocalizations/{localization_id}/appScreenshotSets"
        "?fields[appScreenshotSets]=screenshotDisplayType"
    )


def replace_screenshot_set(
    client: AppStoreConnectClient,
    localization_id: str,
    display_type: str,
    dry_run: bool,
) -> str:
    existing_sets = list_screenshot_sets(client, localization_id)
    for screenshot_set in existing_sets:
        if screenshot_set.get("attributes", {}).get("screenshotDisplayType") != display_type:
            continue

        if dry_run:
            print(f"DRY RUN: would delete existing screenshot set {screenshot_set['id']} ({display_type})")
        else:
            print(f"Deleting existing screenshot set {screenshot_set['id']} ({display_type})...")
            client.request("DELETE", f"/appScreenshotSets/{screenshot_set['id']}")

    if dry_run:
        print(f"DRY RUN: would create screenshot set {display_type}")
        return f"dry-run-set-{display_type}"

    print(f"Creating screenshot set {display_type}...")
    return client.request(
        "POST",
        "/appScreenshotSets",
        json={
            "data": {
                "type": "appScreenshotSets",
                "attributes": {"screenshotDisplayType": display_type},
                "relationships": {
                    "appStoreVersionLocalization": {
                        "data": {"type": "appStoreVersionLocalizations", "id": localization_id},
                    }
                },
            }
        },
    )["data"]["id"]


def upload_screenshot(client: AppStoreConnectClient, set_id: str, image_path: Path, dry_run: bool) -> str:
    checksum = md5_hex(image_path)
    file_size = image_path.stat().st_size

    if dry_run:
        print(f"DRY RUN: would upload {image_path.name} ({file_size} bytes, md5 {checksum})")
        return f"dry-run-screenshot-{image_path.stem}"

    reservation = client.request(
        "POST",
        "/appScreenshots",
        json={
            "data": {
                "type": "appScreenshots",
                "attributes": {
                    "fileSize": file_size,
                    "fileName": image_path.name,
                },
                "relationships": {
                    "appScreenshotSet": {
                        "data": {"type": "appScreenshotSets", "id": set_id},
                    }
                },
            }
        },
    )["data"]

    screenshot_id = reservation["id"]
    operations = reservation.get("attributes", {}).get("uploadOperations", [])
    if not operations:
        raise AppStoreConnectError(f"No upload operations returned for {image_path}")

    for operation in operations:
        client.upload_operation(operation, image_path)

    client.request(
        "PATCH",
        f"/appScreenshots/{screenshot_id}",
        json={
            "data": {
                "type": "appScreenshots",
                "id": screenshot_id,
                "attributes": {
                    "uploaded": True,
                    "sourceFileChecksum": checksum,
                },
            }
        },
    )

    return screenshot_id


def order_screenshots(client: AppStoreConnectClient, set_id: str, screenshot_ids: list[str], dry_run: bool) -> None:
    if dry_run:
        print(f"DRY RUN: would order {len(screenshot_ids)} screenshot(s) in set {set_id}")
        return

    client.request(
        "PATCH",
        f"/appScreenshotSets/{set_id}/relationships/appScreenshots",
        json={"data": [{"type": "appScreenshots", "id": screenshot_id} for screenshot_id in screenshot_ids]},
    )


def wait_for_processing(client: AppStoreConnectClient, screenshot_ids: list[str], timeout_seconds: int, dry_run: bool) -> None:
    if dry_run or timeout_seconds <= 0:
        return

    deadline = time.time() + timeout_seconds
    remaining = set(screenshot_ids)
    while remaining and time.time() < deadline:
        complete = set()
        for screenshot_id in sorted(remaining):
            screenshot = client.request(
                "GET",
                f"/appScreenshots/{screenshot_id}?fields[appScreenshots]=assetDeliveryState",
            )["data"]
            state = screenshot.get("attributes", {}).get("assetDeliveryState", {}).get("state")
            if state in {"COMPLETE", "UPLOAD_COMPLETE"}:
                complete.add(screenshot_id)
            elif state == "FAILED":
                raise AppStoreConnectError(f"Screenshot {screenshot_id} failed App Store processing")

        remaining -= complete
        if remaining:
            print(f"Waiting for {len(remaining)} screenshot(s) to finish processing...")
            time.sleep(5)

    if remaining:
        raise AppStoreConnectError(f"Timed out waiting for {len(remaining)} screenshot(s) to finish processing")


def list_set_screenshot_ids(client: AppStoreConnectClient, set_id: str) -> list[str]:
    screenshots = client.get_all(
        f"/appScreenshotSets/{set_id}/appScreenshots?fields[appScreenshots]=fileName"
    )
    return [screenshot["id"] for screenshot in screenshots]


def verify_screenshot_order(
    client: AppStoreConnectClient,
    set_id: str,
    expected_ids: list[str],
    dry_run: bool,
) -> None:
    if dry_run or not expected_ids:
        return

    if list_set_screenshot_ids(client, set_id) == expected_ids:
        return

    print(f"Screenshot order mismatch in set {set_id}; re-applying intended order...")
    order_screenshots(client, set_id, expected_ids, dry_run)

    if list_set_screenshot_ids(client, set_id) != expected_ids:
        print(
            f"WARNING: App Store Connect still reports a different screenshot order for set {set_id} "
            "after re-applying. Check the order manually.",
            file=sys.stderr,
        )


def grouped_images(locale_dir: Path) -> dict[str, list[Path]]:
    images = sorted(
        [path for path in locale_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS],
        key=image_sort_key,
    )
    if not images:
        raise AppStoreConnectError(f"No screenshot images found in {locale_dir}")

    groups: dict[str, list[Path]] = {}
    for image in images:
        display_type = display_type_for_image(image)
        groups.setdefault(display_type, []).append(image)
    return groups


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload App Store screenshots through App Store Connect API.")
    parser.add_argument("--locale", required=True, help="App Store Connect locale, for example en-US.")
    parser.add_argument("--screenshots-path", required=True, type=Path, help="Directory containing locale folders.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve app/version/localization and print actions only.")
    return parser.parse_args()


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from log import log_debug, log_info, log_step, log_step_done, log_warn

    args = parse_args()
    locale_dir = args.screenshots_path / args.locale
    if not locale_dir.is_dir():
        raise AppStoreConnectError(f"Missing locale screenshot directory: {locale_dir}")

    log_step(f"Screenshot API upload: {args.locale}")
    log_info(f"Screenshots path: {locale_dir}")
    dry_run = args.dry_run or env_bool("SCREENSHOT_API_DRY_RUN")
    if dry_run:
        log_warn("Screenshot API dry-run enabled")
    key_path = Path(require_env("ASC_KEY_PATH"))
    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=key_path,
        timeout=env_int("SCREENSHOT_API_REQUEST_TIMEOUT", 60),
        max_retries=env_int("SCREENSHOT_API_MAX_RETRIES", 5),
    )

    app = find_app(client, require_env("APP_IDENTIFIER"))
    log_info(f"Resolved app id: {app['id']}")
    version = find_editable_version(client, app["id"])
    version_attributes = version.get("attributes", {})
    log_info(
        "Using app store version "
        f"{version_attributes.get('versionString')} ({version_attributes.get('appStoreState')})"
    )

    localization = find_or_create_localization(client, version["id"], args.locale, dry_run)
    log_info(f"Using localization id {localization['id']} for {args.locale}")
    groups = grouped_images(locale_dir)
    processing_timeout = env_int("SCREENSHOT_API_PROCESSING_TIMEOUT", 180)
    log_info(f"Screenshot groups: {', '.join(f'{key}={len(value)}' for key, value in sorted(groups.items()))}")

    for display_type, images in sorted(groups.items()):
        log_info(f"Uploading {len(images)} screenshot(s) for {args.locale} / {display_type}...")
        set_id = replace_screenshot_set(client, localization["id"], display_type, dry_run)
        # Upload one screenshot at a time and wait for each to finish processing before
        # sending the next. App Store Connect orders a batch by processing-completion time,
        # so a parallel upload comes out shuffled; sequential upload keeps the intended order.
        screenshot_ids: list[str] = []
        for position, image in enumerate(images, start=1):
            log_info(
                f"Screenshot {position}/{len(images)} for {args.locale} / {display_type}: "
                f"{image.name} ({image.stat().st_size} bytes)"
            )
            screenshot_id = upload_screenshot(client, set_id, image, dry_run)
            wait_for_processing(client, [screenshot_id], processing_timeout, dry_run)
            screenshot_ids.append(screenshot_id)
        # Pin the final display order once every screenshot is processed, then confirm it stuck.
        order_screenshots(client, set_id, screenshot_ids, dry_run)
        verify_screenshot_order(client, set_id, screenshot_ids, dry_run)

    log_info(f"Uploaded screenshots for {args.locale} through App Store Connect API.")
    log_step_done(f"Screenshot API upload: {args.locale}", 0)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AppStoreConnectError as error:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        from log import log_error, log_step_done

        log_error(f"Screenshot API upload failed: {error}")
        log_step_done("Screenshot API upload", 1)
        raise SystemExit(1)
