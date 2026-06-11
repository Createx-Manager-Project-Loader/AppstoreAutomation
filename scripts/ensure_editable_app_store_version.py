#!/usr/bin/env python3
"""Ensure an editable iOS App Store version exists, creating the next minor version if needed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from upload_screenshots_api import (  # noqa: E402
    AppStoreConnectClient,
    AppStoreConnectError,
    ensure_editable_app_store_version,
    env_bool,
    find_app,
    require_env,
)


def main() -> int:
    sys.path.insert(0, str(SCRIPT_DIR / "lib"))
    from log import log_debug, log_info, log_step, log_step_done

    log_step("Ensure editable App Store version")
    auto_create = env_bool("AUTO_CREATE_APP_STORE_VERSION", True)
    log_info(f"AUTO_CREATE_APP_STORE_VERSION={auto_create}")
    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=Path(require_env("ASC_KEY_PATH")),
    )
    app = find_app(client, require_env("APP_IDENTIFIER"))
    try:
        version = ensure_editable_app_store_version(client, app["id"], auto_create=auto_create)
    except AppStoreConnectError as error:
        from log import log_error

        log_error(str(error))
        log_step_done("Ensure editable App Store version", 1)
        return 1

    attributes = version.get("attributes", {})
    version_string = attributes.get("versionString", "unknown")
    version_state = attributes.get("appStoreState", "unknown")
    log_info(f"Using editable App Store version {version_string} ({version_state}).")
    log_info(f"Editable version id: {version['id']}")

    sys.path.insert(0, str(SCRIPT_DIR / "lib"))
    from automation_report import merge_section  # noqa: E402

    merge_section(
        "app_store_version",
        {
            "version_string": version_string,
            "app_store_state": version_state,
            "auto_create_enabled": auto_create,
        },
    )
    log_step_done("Ensure editable App Store version", 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
