#!/usr/bin/env python3
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from prepare_metadata import LOCALE_RE, METADATA_DIR  # noqa: E402
from upload_screenshots_api import (  # noqa: E402
    AppStoreConnectClient,
    AppStoreConnectError,
    find_app,
    find_editable_version,
    require_env,
)


def resolve_metadata_dir() -> Path:
    env_path = os.environ.get("METADATA_DIR", "").strip()
    if env_path:
        return Path(env_path)
    return METADATA_DIR


def main() -> int:
    metadata_dir = resolve_metadata_dir()
    key_path = Path(require_env("ASC_KEY_PATH"))
    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=key_path,
        timeout=60,
        max_retries=5,
    )

    app = find_app(client, require_env("APP_IDENTIFIER"))
    version = find_editable_version(client, app["id"])
    version_attributes = version.get("attributes", {})
    print(
        "Bootstrapping metadata locales from editable app store version "
        f"{version_attributes.get('versionString')} ({version_attributes.get('appStoreState')})"
    )

    localizations = client.get_all(
        f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations"
        "?fields[appStoreVersionLocalizations]=locale"
    )

    locales = []
    for localization in localizations:
        locale = localization.get("attributes", {}).get("locale")
        if not locale or not LOCALE_RE.match(locale):
            continue
        (metadata_dir / locale).mkdir(parents=True, exist_ok=True)
        locales.append(locale)

    if not locales:
        raise AppStoreConnectError("No app store version localizations found for the editable version")

    print(f"Created metadata locale folders for {len(locales)} locale(s) in {metadata_dir}.")

    sys.path.insert(0, str(SCRIPT_DIR / "lib"))
    from automation_report import merge_section

    merge_section("whats_new", {"bootstrap_locales": len(locales), "bootstrap_source": "editable_version"})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AppStoreConnectError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
