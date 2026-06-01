#!/usr/bin/env python3
import sys
from pathlib import Path

from prepare_metadata import (
    METADATA_DIR,
    PREPARED_SCREENSHOTS_DIR,
    LOCALE_RE,
    REPO_ROOT,
    get_release_notes_fallback,
    has_aso_source,
    has_screenshots_source,
    read_aso_rows,
    read_description_rows,
    read_subscription_rows,
    resolve_run_plan,
    subscription_locale_count,
    subscription_rows_by_product,
)
from release_notes import resolve_release_notes_for_locales

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


def validate_required_values(rows, fields, source_name, errors):
    for locale, row in rows.items():
        for field in fields:
            value = row.get(field, "")
            if not value:
                errors.append(f"{source_name}:{locale} has empty {field}")


def validate_subscription_rows(rows, errors):
    if subscription_rows_by_product(rows):
        for product_id, locales in rows.items():
            for locale, row in locales.items():
                prefix = f"Subs:{product_id}:{locale}"
                _validate_subscription_locale_row(row, prefix, errors)
        return

    for locale, row in rows.items():
        _validate_subscription_locale_row(row, f"Subs:{locale}", errors)


def _validate_subscription_locale_row(row, prefix, errors):
    name = row.get("name", "").strip()
    description = row.get("description", "").strip()
    if not name:
        errors.append(f"{prefix} has empty subscription name")
    if len(name) > SUBSCRIPTION_LIMITS["name"]:
        errors.append(
            f"{prefix} subscription name is {len(name)} chars; max is {SUBSCRIPTION_LIMITS['name']}"
        )
    if description and len(description) > SUBSCRIPTION_LIMITS["description"]:
        errors.append(
            f"{prefix} subscription description is {len(description)} chars; "
            f"max is {SUBSCRIPTION_LIMITS['description']}"
        )


def validate_limits(aso_rows, description_rows, errors):
    for locale, row in aso_rows.items():
        for field in ("title", "subtitle", "keywords"):
            value = row.get(field, "")
            if len(value) > LIMITS[field]:
                errors.append(f"{locale} {field} is {len(value)} chars; max is {LIMITS[field]}")
        if "\n" in row.get("keywords", ""):
            errors.append(f"{locale} keywords must be a single line")

    for locale, row in description_rows.items():
        value = row.get("description", "")
        if len(value) > LIMITS["description"]:
            errors.append(f"{locale} description is {len(value)} chars; max is {LIMITS['description']}")


def prepared_screenshot_locales():
    if not PREPARED_SCREENSHOTS_DIR.exists():
        return set()
    return {path.name for path in PREPARED_SCREENSHOTS_DIR.iterdir() if path.is_dir() and LOCALE_RE.match(path.name)}


def resolve_metadata_dir():
    import os

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
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from automation_report import add_message, merge_section

    warning_messages = fields.pop("warning_messages", [])
    merge_section("validation", fields)
    for warning in warning_messages:
        add_message("warnings", warning)


def main():
    errors = []
    warnings = []
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
    run_subscriptions = plan.get("run_subscriptions", False)
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

        subscription_rows = read_subscription_rows()
        if subscription_rows:
            validate_subscription_rows(subscription_rows, errors)

        if not aso_rows:
            errors.append("ASO input has no locale rows")

        validate_required_values(aso_rows, ["title", "subtitle", "keywords"], "Google Sheet ASO", errors)
        if description_rows:
            validate_required_values(description_rows, ["description"], "Google Sheet descriptions", errors)
        validate_limits(aso_rows, description_rows, errors)

    screenshot_locales = prepared_screenshot_locales()
    if prepare_screenshots and not screenshot_locales:
        errors.append("No prepared screenshots found. Run scripts/prepare_metadata.sh before validation.")

    if run_whats_new:
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

    print(f"Validation passed for RUN_MODE={mode}.")
    record_validation_report(**validation_fields)


if __name__ == "__main__":
    main()
