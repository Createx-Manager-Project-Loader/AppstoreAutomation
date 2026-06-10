#!/usr/bin/env python3
"""Collects automation run statistics and prints a final summary."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LIB_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = LIB_DIR.parent

from paths import PREPARED_DIR, REPO_ROOT
REPORT_PATH = PREPARED_DIR / "automation_report.json"

LOCALE_RE_IMPORT = None


def locale_pattern():
    global LOCALE_RE_IMPORT
    if LOCALE_RE_IMPORT is None:
        sys.path.insert(0, str(SCRIPT_DIR))
        from prepare_metadata import LOCALE_RE

        LOCALE_RE_IMPORT = LOCALE_RE
    return LOCALE_RE_IMPORT


def metadata_dir() -> Path:
    env_path = os.environ.get("METADATA_DIR", "").strip()
    if env_path:
        return Path(env_path)
    return REPO_ROOT / "metadata"


def count_locale_dirs(root: Path) -> int:
    if not root.is_dir():
        return 0
    pattern = locale_pattern()
    return sum(1 for path in root.iterdir() if path.is_dir() and pattern.match(path.name))


def list_locale_dirs(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    pattern = locale_pattern()
    return sorted(path.name for path in root.iterdir() if path.is_dir() and pattern.match(path.name))


def load_report() -> dict[str, Any]:
    if not REPORT_PATH.is_file():
        return {}
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def default_report() -> dict[str, Any]:
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "status": "running",
        "run_mode": "",
        "plan": {},
        "errors": [],
        "warnings": [],
        "sections": {},
    }


def init_report() -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    from prepare_metadata import resolve_run_plan

    plan = resolve_run_plan()
    report = default_report()
    report["run_mode"] = plan.get("mode", "")
    report["plan"] = plan
    save_report(report)


def merge_section(section: str, updates: dict[str, Any]) -> None:
    report = load_report() or default_report()
    sections = report.setdefault("sections", {})
    current = sections.setdefault(section, {})
    if not isinstance(current, dict):
        current = {}
        sections[section] = current
    current.update(updates)
    save_report(report)


def add_message(kind: str, message: str) -> None:
    report = load_report() or default_report()
    bucket = report.setdefault(kind, [])
    if message not in bucket:
        bucket.append(message)
    save_report(report)


def set_status(status: str) -> None:
    report = load_report() or default_report()
    report["status"] = status
    if status in {"success", "failed", "partial"}:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_report(report)


def _ratio_line(done: int | None, total: int | None, label: str) -> str:
    if total is None or total == 0:
        return f"  {label}: not run"
    done = done if done is not None else 0
    if done >= total:
        return f"  {label}: {done} / {total} (all)"
    return f"  {label}: {done} / {total}"


def _normalize_locale_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part for part in re.split(r"[, \n]+", value.strip()) if part]
    return []


def _list_suffix(items: Any, limit: int = 8) -> str:
    normalized = _normalize_locale_list(items)
    if not normalized:
        return ""
    shown = normalized[:limit]
    suffix = ", ".join(shown)
    if len(normalized) > limit:
        suffix += f", … (+{len(normalized) - limit} more)"
    return f" [{suffix}]"


def print_final_report() -> int:
    report = load_report()
    if not report:
        print("No automation report was generated for this run.")
        return 0

    width = 72
    border = "═" * width
    thin = "─" * (width - 2)

    status = report.get("status", "unknown")
    status_label = {
        "success": "SUCCESS",
        "partial": "PARTIAL (some steps failed; other uploads may have succeeded)",
        "failed": "FAILED",
        "running": "INCOMPLETE",
    }.get(status, status.upper())

    lines: list[str] = [
        border,
        "  APP STORE AUTOMATION — FINAL REPORT",
        border,
        f"  Run mode: {report.get('run_mode') or '—'}",
        f"  Status:   {status_label}",
    ]

    if report.get("started_at"):
        lines.append(f"  Started:  {report['started_at']}")
    if report.get("finished_at"):
        lines.append(f"  Finished: {report['finished_at']}")

    plan = report.get("plan") or {}
    if plan:
        enabled = [key.replace("run_", "").replace("prepare_", "prepare ") for key, value in plan.items() if key != "mode" and value]
        if enabled:
            lines.append(f"  Plan:     {', '.join(enabled)}")

    sections = report.get("sections") or {}

    def section_header(title: str) -> None:
        lines.append("")
        lines.append(f"  {title}")
        lines.append(f"  {thin}")

    prepare = sections.get("prepare") or {}
    if prepare or plan.get("prepare_aso") or plan.get("prepare_screenshots"):
        section_header("Preparation")
        if prepare.get("aso_skipped"):
            lines.append("  ASO metadata: skipped (no google_sheet_url)")
        elif "aso_locales" in prepare:
            desc = prepare.get("description_locales")
            aso = prepare.get("aso_locales", 0)
            aso_source = prepare.get("aso_url_source")
            lines.append(f"  ASO metadata: {aso} locale(s) prepared")
            if aso_source and aso_source != "none":
                lines.append(f"  ASO URL source: {aso_source}")
            if desc is not None:
                lines.append(f"  Descriptions: {desc} locale(s) prepared")
            if prepare.get("version_url_files"):
                lines.append(f"  Support/Marketing URLs: {prepare['version_url_files']} file(s) prepared")
        if prepare.get("screenshots_skipped"):
            lines.append("  Screenshots:  skipped (no screenshots_zip_url)")
        elif "subscription_locales" in prepare and prepare.get("subscription_locales"):
            lines.append(f"  Subscription locales prepared: {prepare['subscription_locales']}")
        elif "screenshot_locales" in prepare:
            files = prepare.get("screenshot_files", 0)
            locales = prepare.get("screenshot_locales", 0)
            shots_source = prepare.get("screenshots_url_source")
            lines.append(f"  Screenshots:  {files} file(s) across {locales} locale(s)")
            if shots_source and shots_source != "none":
                lines.append(f"  Screenshots URL source: {shots_source}")

    validation = sections.get("validation") or {}
    if validation:
        section_header("Validation")
        if validation.get("passed"):
            lines.append("  Result: PASSED")
        else:
            lines.append("  Result: FAILED")
        if validation.get("mode"):
            lines.append(f"  Mode:   {validation['mode']}")
        for key, label in (
            ("aso_locales", "ASO locales checked"),
            ("description_locales", "Description locales"),
            ("screenshot_locales", "Screenshot locales"),
            ("whats_new_locales", "What's New locales"),
        ):
            if key in validation:
                lines.append(f"  {label}: {validation[key]}")

    metadata = sections.get("metadata_upload") or {}
    if metadata or plan.get("run_metadata"):
        section_header("Metadata upload (subtitle, keywords, description, release notes)")
        if metadata.get("skipped"):
            reason = metadata.get("reason", "")
            if reason == "run_metadata_false":
                lines.append("  Skipped (RUN_METADATA=false)")
            else:
                lines.append("  Skipped")
        elif metadata.get("status") == "success":
            items = metadata.get("items", "")
            total = metadata.get("total", metadata.get("locales", "—"))
            uploaded = metadata.get("uploaded", metadata.get("locales", 0))
            lines.append(_ratio_line(uploaded, total, "Uploaded"))
            if items:
                lines.append(f"  Items:  {items}")
        elif metadata.get("status") in {"failed", "partial"}:
            total = metadata.get("total", 0)
            uploaded = metadata.get("uploaded", 0)
            failed = metadata.get("failed", 0)
            lines.append(_ratio_line(uploaded, total, "Uploaded"))
            if failed:
                lines.append(f"  Failed: {failed}{_list_suffix(metadata.get('failed_locales', []))}")
            if metadata.get("error"):
                lines.append(f"  Error:  {metadata['error']}")

    app_info = sections.get("app_info") or {}
    if app_info or plan.get("run_app_info"):
        section_header("App name / subtitle upload")
        if app_info.get("skipped"):
            reason = app_info.get("reason", "")
            if reason == "run_app_info_false":
                lines.append("  Skipped (RUN_APP_INFO=false)")
            else:
                lines.append("  Skipped")
        else:
            total = app_info.get("total", 0)
            uploaded = app_info.get("uploaded", 0)
            failed = app_info.get("failed", 0)
            skipped = app_info.get("skipped_locales", 0)
            lines.append(_ratio_line(uploaded, total, "Uploaded"))
            if skipped:
                lines.append(f"  Skipped (empty name): {skipped}")
            if failed:
                lines.append(f"  Failed: {failed}{_list_suffix(app_info.get('failed_locales', []))}")

    subscriptions = sections.get("subscriptions") or {}
    if subscriptions or plan.get("run_subscriptions"):
        section_header("Subscription localizations")
        if subscriptions.get("skipped") is True:
            reason = subscriptions.get("reason", "")
            if reason == "no_prepared_data":
                lines.append("  Skipped (no Subs/Subscription sheet in workbook)")
            elif reason == "run_subscriptions_false":
                lines.append("  Skipped (RUN_SUBSCRIPTIONS=false)")
            else:
                lines.append("  Skipped")
        else:
            product_id = subscriptions.get("product_id", "—")
            lines.append(f"  Product id: {product_id}")
            lines.append(_ratio_line(subscriptions.get("uploaded"), subscriptions.get("total"), "Uploaded"))
            if subscriptions.get("created"):
                lines.append(f"  Created: {subscriptions['created']}")
            if subscriptions.get("updated"):
                lines.append(f"  Updated: {subscriptions['updated']}")
            unchanged = subscriptions.get("unchanged", subscriptions.get("skipped"))
            if isinstance(unchanged, int) and unchanged:
                lines.append(f"  Unchanged: {unchanged}")

    screenshots = sections.get("screenshots") or {}
    if screenshots or plan.get("run_screenshots"):
        section_header("Screenshot upload")
        if screenshots.get("skipped"):
            reason = screenshots.get("reason", "")
            if reason == "run_screenshots_false":
                lines.append("  Skipped (RUN_SCREENSHOTS=false)")
            else:
                lines.append("  Skipped")
        else:
            total = screenshots.get("total", 0)
            uploaded = screenshots.get("uploaded", 0)
            failed = screenshots.get("failed", 0)
            lines.append(_ratio_line(uploaded, total, "Uploaded"))
            if failed:
                lines.append(f"  Failed: {failed}{_list_suffix(screenshots.get('failed_locales', []))}")

    whats_new = sections.get("whats_new") or {}
    if whats_new or plan.get("run_whats_new"):
        section_header("What's New")
        if whats_new.get("skipped"):
            reason = whats_new.get("reason", "")
            if reason == "run_whats_new_false":
                lines.append("  Skipped (RUN_WHATS_NEW=false; may upload via metadata when RUN_METADATA=true)")
            else:
                lines.append("  Skipped")
        else:
            if "locales_total" in whats_new:
                prepared = whats_new.get("release_notes_prepared", whats_new.get("locales_total"))
                lines.append(_ratio_line(prepared, whats_new["locales_total"], "Release notes prepared"))
            if "uploaded" in whats_new:
                lines.append(_ratio_line(whats_new.get("uploaded"), whats_new.get("locales_total"), "Uploaded"))
            if whats_new.get("failed"):
                lines.append(f"  Failed: {whats_new['failed']}{_list_suffix(whats_new.get('failed_locales', []))}")
            if whats_new.get("bootstrap_locales"):
                lines.append(f"  Bootstrapped locale folders: {whats_new['bootstrap_locales']}")
            if whats_new.get("source_live"):
                lines.append(f"  From live App Store: {whats_new['source_live']} locale(s)")
            if whats_new.get("source_base"):
                lines.append(f"  From base locale: {whats_new['source_base']} locale(s)")
            if whats_new.get("source_config"):
                lines.append(f"  From fallback (config/workflow): {whats_new['source_config']} locale(s)")
            if whats_new.get("urls_prepared"):
                lines.append(f"  Support/Marketing URL files prepared: {whats_new['urls_prepared']}")
            if whats_new.get("urls_source_primary"):
                lines.append(f"  URLs from primary released locale: {whats_new['urls_source_primary']} locale(s)")
            if whats_new.get("urls_source_fallback"):
                lines.append(f"  URLs from fallback released locale: {whats_new['urls_source_fallback']} locale(s)")
            if whats_new.get("urls_source_live"):
                lines.append(f"  URLs from live App Store: {whats_new['urls_source_live']} locale(s)")
            if whats_new.get("urls_source_base"):
                lines.append(f"  URLs from base locale: {whats_new['urls_source_base']} locale(s)")
            upload_status = whats_new.get("upload_status")
            if upload_status:
                label = "SUCCESS" if upload_status == "success" else "FAILED"
                lines.append(f"  Upload to App Store Connect: {label}")

    warnings = report.get("warnings") or []
    errors = report.get("errors") or []

    if warnings:
        section_header(f"Warnings ({len(warnings)})")
        for warning in warnings:
            lines.append(f"  • {warning}")

    if errors:
        section_header(f"Errors ({len(errors)})")
        for error in errors:
            lines.append(f"  • {error}")

    lines.append(border)

    output = "\n".join(lines)
    stream = sys.stderr if status in {"failed", "partial"} else sys.stdout
    print(output, file=stream)
    return 1 if status in {"failed", "partial"} else 0


def cmd_init(_: argparse.Namespace) -> int:
    init_report()
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    updates: dict[str, Any] = {}
    for item in args.fields:
        if "=" not in item:
            raise SystemExit(f"Expected key=value, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.lower() in {"true", "false"}:
            updates[key] = value.lower() == "true"
        elif value.isdigit():
            updates[key] = int(value)
        else:
            try:
                if value.startswith("[") or value.startswith("{"):
                    updates[key] = json.loads(value)
                else:
                    updates[key] = value
            except json.JSONDecodeError:
                updates[key] = value
    merge_section(args.section, updates)
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    add_message(args.kind, args.message)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    set_status(args.status)
    return 0


def cmd_print(_: argparse.Namespace) -> int:
    return print_final_report()


def main() -> int:
    parser = argparse.ArgumentParser(description="Automation run report")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    merge = sub.add_parser("merge-section")
    merge.add_argument("section")
    merge.add_argument("fields", nargs="+", metavar="key=value")
    merge.set_defaults(func=cmd_merge)

    add = sub.add_parser("add")
    add.add_argument("kind", choices=["errors", "warnings"])
    add.add_argument("message")
    add.set_defaults(func=cmd_add)

    status = sub.add_parser("set-status")
    status.add_argument("status", choices=["running", "success", "partial", "failed"])
    status.set_defaults(func=cmd_status)

    sub.add_parser("print-final").set_defaults(func=cmd_print)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
