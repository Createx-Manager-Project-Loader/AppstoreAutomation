#!/usr/bin/env python3
import json
import os
import shutil
import sys
from pathlib import Path

from prepare_metadata import (
    METADATA_DIR,
    PREPARED_SCREENSHOTS_DIR,
    PREPARED_SUBSCRIPTION_PATH,
    LOCALE_RE,
    REPO_ROOT,
    get_release_notes_fallback,
    read_aso_rows,
    read_description_rows,
    read_subscription_rows,
    resolve_run_plan,
    subscription_locale_count,
    subscription_rows_by_product,
)
from release_notes import resolve_release_notes_for_locales

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from paths import PREPARED_DIR

LIMITS = {
    "title": 30,
    "subtitle": 30,
    "keywords": 100,
    "description": 4000,
}

SUBSCRIPTION_LIMITS = {
    "name": 30,
    "description": 45,
}

EXCLUDED_LOCALES_PATH = PREPARED_DIR / "excluded_locales.json"


def is_strict_validation() -> bool:
    return os.environ.get("VALIDATION_STRICT", "").lower() in {"1", "true", "yes", "on"}


def collect_aso_locale_issues(aso_rows, description_rows) -> dict[str, list[str]]:
    issues: dict[str, list[str]] = {}

    def note(locale: str, message: str) -> None:
        issues.setdefault(locale, []).append(message)

    for locale, row in aso_rows.items():
        for field in ("title", "subtitle", "keywords"):
            value = row.get(field, "").strip()
            if not value:
                continue
            if len(value) > LIMITS[field]:
                note(locale, f"{field} is {len(value)} chars; max is {LIMITS[field]}")
        if "\n" in row.get("keywords", ""):
            note(locale, "keywords must be a single line")

    if description_rows:
        for locale, row in description_rows.items():
            value = row.get("description", "").strip()
            if value and len(value) > LIMITS["description"]:
                note(locale, f"description is {len(value)} chars; max is {LIMITS['description']}")

    metadata_dir = resolve_metadata_dir()
    if metadata_dir.exists():
        for locale_dir in metadata_dir.iterdir():
            if not locale_dir.is_dir() or not LOCALE_RE.match(locale_dir.name):
                continue
            description_path = locale_dir / "description.txt"
            if not description_path.is_file():
                continue
            value = description_path.read_text(encoding="utf-8").strip()
            if len(value) > LIMITS["description"]:
                note(
                    locale_dir.name,
                    f"description is {len(value)} chars; max is {LIMITS['description']}",
                )

    return issues


def collect_subscription_locale_issues(rows) -> dict[str, list[str]]:
    issues: dict[str, list[str]] = {}

    def note(locale: str, message: str) -> None:
        issues.setdefault(locale, []).append(message)

    def check_row(locale: str, row: dict) -> None:
        name = row.get("name", "").strip()
        description = row.get("description", "").strip()
        if not name:
            note(locale, "empty subscription name")
        elif len(name) > SUBSCRIPTION_LIMITS["name"]:
            note(
                locale,
                f"subscription name is {len(name)} chars; max is {SUBSCRIPTION_LIMITS['name']}",
            )
        if description and len(description) > SUBSCRIPTION_LIMITS["description"]:
            note(
                locale,
                f"subscription description is {len(description)} chars; "
                f"max is {SUBSCRIPTION_LIMITS['description']}",
            )

    if subscription_rows_by_product(rows):
        for _product_id, locales in rows.items():
            for locale, row in locales.items():
                check_row(locale, row)
        return issues

    for locale, row in rows.items():
        check_row(locale, row)
    return issues


def merge_locale_issues(*issue_maps: dict[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for issue_map in issue_maps:
        for locale, messages in issue_map.items():
            merged.setdefault(locale, []).extend(messages)
    return merged


def apply_locale_exclusions(excluded: dict[str, list[str]]) -> None:
    if not excluded:
        if EXCLUDED_LOCALES_PATH.exists():
            EXCLUDED_LOCALES_PATH.unlink()
        return

    PREPARED_DIR.mkdir(parents=True, exist_ok=True)
    EXCLUDED_LOCALES_PATH.write_text(
        json.dumps(excluded, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    metadata_dir = resolve_metadata_dir()
    for locale in excluded:
        locale_dir = metadata_dir / locale
        if locale_dir.is_dir():
            shutil.rmtree(locale_dir)
            print(f"Skipped locale {locale}: removed prepared metadata ({'; '.join(excluded[locale])}).")

    filter_prepared_subscription_locales(set(excluded))


def filter_prepared_subscription_locales(excluded_locales: set[str]) -> None:
    if not excluded_locales or not PREPARED_SUBSCRIPTION_PATH.is_file():
        return

    payload = json.loads(PREPARED_SUBSCRIPTION_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        return

    sample_value = payload[next(iter(payload))]
    changed = False

    if isinstance(sample_value, dict) and "name" in sample_value:
        for locale in sorted(excluded_locales):
            if locale in payload:
                del payload[locale]
                changed = True
                print(f"Skipped subscription locale {locale}.")
    elif isinstance(sample_value, dict):
        for product_id, locales in payload.items():
            if not isinstance(locales, dict):
                continue
            for locale in sorted(excluded_locales):
                if locale in locales:
                    del locales[locale]
                    changed = True
                    print(f"Skipped subscription locale {locale} for product {product_id}.")
            if not locales:
                del payload[product_id]

    if changed:
        if payload:
            PREPARED_SUBSCRIPTION_PATH.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        else:
            PREPARED_SUBSCRIPTION_PATH.unlink()


def prepared_screenshot_locales():
    if not PREPARED_SCREENSHOTS_DIR.exists():
        return set()
    return {path.name for path in PREPARED_SCREENSHOTS_DIR.iterdir() if path.is_dir() and LOCALE_RE.match(path.name)}


def resolve_metadata_dir():
    env_path = os.environ.get("METADATA_DIR", "").strip()
    if env_path:
        return Path(env_path)
    return METADATA_DIR


def metadata_locales():
    metadata_dir = resolve_metadata_dir()
    if not metadata_dir.exists():
        return []
    return sorted(path.name for path in metadata_dir.iterdir() if path.is_dir() and LOCALE_RE.match(path.name))


def validate_whats_new(errors, locales=None):
    if locales is None:
        locales = metadata_locales()
    if not locales:
        errors.append(
            f"No locale folders found in {resolve_metadata_dir()}. "
            "Run ensure_whats_new_locales.sh or bootstrap_metadata_locales.py first."
        )
        return

    resolved, _stats = resolve_release_notes_for_locales(locales, REPO_ROOT, get_release_notes_fallback())
    if not resolved:
        errors.append("No What's New text found in live App Store version, base locale, or config release_notes")


def record_validation_report(**fields) -> None:
    from automation_report import add_message, merge_section

    warning_messages = fields.pop("warning_messages", [])
    merge_section("validation", fields)
    for warning in warning_messages:
        add_message("warnings", warning)


def main():
    errors = []
    warnings = []
    locale_issues: dict[str, list[str]] = {}

    if os.environ.get("WHATS_NEW_VALIDATE_ONLY", "").lower() in {"1", "true", "yes", "on"}:
        validate_whats_new(errors)
        locales = metadata_locales()
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            record_validation_report(
                passed=False,
                mode="whats_new",
                whats_new_locales=len(locales),
            )
            sys.exit(1)
        print("Validation passed for What's New upload.")
        record_validation_report(
            passed=True,
            mode="whats_new",
            whats_new_locales=len(locales),
        )
        return

    plan = resolve_run_plan()
    mode = plan["mode"]

    if mode == "whats_new":
        validate_whats_new(errors)
        locales = metadata_locales()
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            record_validation_report(
                passed=False,
                mode=mode,
                whats_new_locales=len(locales),
            )
            sys.exit(1)
        print("Validation passed for What's New only mode.")
        record_validation_report(
            passed=True,
            mode=mode,
            whats_new_locales=len(locales),
        )
        return

    prepare_aso = plan["prepare_aso"]
    prepare_screenshots = plan["prepare_screenshots"]
    run_whats_new = plan["run_whats_new"]

    aso_rows = {}
    description_rows = {}
    subscription_rows = {}

    if prepare_aso:
        try:
            aso_rows = read_aso_rows()
        except SystemExit as error:
            errors.append(str(error))

        try:
            description_rows = read_description_rows()
        except SystemExit as error:
            errors.append(str(error))

        if not errors:
            subscription_rows = read_subscription_rows()
            if subscription_rows:
                locale_issues = merge_locale_issues(
                    locale_issues,
                    collect_subscription_locale_issues(subscription_rows),
                )

            if not aso_rows:
                errors.append("ASO input has no locale rows")
            else:
                locale_issues = merge_locale_issues(
                    locale_issues,
                    collect_aso_locale_issues(aso_rows, description_rows),
                )

    screenshot_locales = prepared_screenshot_locales()
    if prepare_screenshots and not screenshot_locales:
        errors.append("No prepared screenshots found. Run scripts/prepare_metadata.sh before validation.")

    if run_whats_new and not errors:
        locales = sorted(screenshot_locales) if screenshot_locales else metadata_locales()
        if not locales and mode == "all" and not prepare_screenshots:
            locales = metadata_locales()
        if not locales:
            errors.append("No locales found for What's New validation.")
        else:
            resolved, _stats = resolve_release_notes_for_locales(locales, REPO_ROOT, get_release_notes_fallback())
            if not resolved:
                errors.append(
                    "No What's New text found in live App Store version, base locale, or config release_notes"
                )

    aso_locales = set(aso_rows)
    description_locales = set(description_rows)

    if prepare_aso and description_rows and aso_locales != description_locales:
        only_aso = sorted(aso_locales - description_locales)
        only_descriptions = sorted(description_locales - aso_locales)
        if only_aso:
            warnings.append("Locales missing from descriptions: " + ", ".join(only_aso))
        if only_descriptions:
            warnings.append("Locales missing from ASO: " + ", ".join(only_descriptions))

    if prepare_aso and prepare_screenshots and screenshot_locales:
        known_locales = aso_locales | description_locales
        unknown = sorted(screenshot_locales - known_locales)
        if unknown:
            warnings.append("Screenshot locales not found in Google Sheet: " + ", ".join(unknown))
        missing = sorted(known_locales - screenshot_locales)
        if missing:
            warnings.append("No screenshots found for Google Sheet locale(s): " + ", ".join(missing))

    excluded_locales: dict[str, list[str]] = {}
    if locale_issues and not errors:
        if is_strict_validation():
            for locale in sorted(locale_issues):
                for message in locale_issues[locale]:
                    errors.append(f"{locale} {message}")
        else:
            excluded_locales = locale_issues
            apply_locale_exclusions(excluded_locales)
            remaining = metadata_locales()
            if prepare_aso and aso_rows and not remaining:
                errors.append(
                    "No valid locales remaining after excluding invalid ASO metadata. "
                    f"Excluded: {', '.join(sorted(excluded_locales))}"
                )
            elif excluded_locales:
                warnings.append(
                    "Excluded invalid locale(s) from upload: "
                    + ", ".join(f"{locale} ({'; '.join(excluded_locales[locale])})" for locale in sorted(excluded_locales))
                )

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    validation_fields = {
        "passed": not errors,
        "mode": mode,
        "warning_messages": warnings,
    }
    if prepare_aso:
        validation_fields["aso_locales"] = len(aso_rows)
        validation_fields["description_locales"] = len(description_rows)
        validation_fields["subscription_locales"] = subscription_locale_count(subscription_rows)
        if excluded_locales:
            validation_fields["excluded_locales"] = len(excluded_locales)
            validation_fields["upload_locales"] = len(metadata_locales())
    if prepare_screenshots:
        validation_fields["screenshot_locales"] = len(screenshot_locales)
    if run_whats_new:
        locales_for_whats_new = sorted(screenshot_locales) if screenshot_locales else metadata_locales()
        validation_fields["whats_new_locales"] = len(locales_for_whats_new)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        record_validation_report(**validation_fields)
        sys.exit(1)

    if excluded_locales:
        print(
            f"Validation passed for RUN_MODE={mode} with {len(excluded_locales)} excluded locale(s); "
            f"continuing upload for {len(metadata_locales())} locale(s)."
        )
    else:
        print(f"Validation passed for RUN_MODE={mode}.")
    record_validation_report(**validation_fields)


if __name__ == "__main__":
    main()
