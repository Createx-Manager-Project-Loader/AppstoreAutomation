#!/usr/bin/env python3
"""Classify upload failures and store per-locale reasons in the automation report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

LIB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(LIB_DIR))

from automation_report import load_report, merge_section, save_report, default_report

CATEGORY_LABELS = {
    "name_rejected": "name rejected",
    "metadata_rejected": "metadata rejected",
    "screenshot_rejected": "screenshot rejected",
    "unknown": "upload failed",
}

NAME_PATTERNS = [
    r"app name.*already",
    r"name.*already (been )?used",
    r"name.*already in use",
    r"already being used by another app",
    r"duplicate_name",
    r"state_error\.duplicate_name",
    r"not available.*app name",
    r"non-unique",
    r"not unique",
    r"name_already_used",
    r"duplicate.*name",
    r"could not update.*name",
]

METADATA_PATTERNS = [
    r"\bkeywords\b",
    r"\bsubtitle\b",
    r"\bdescription\b",
    r"release.?notes",
    r"whats.?new",
    r"marketing[_ ]url",
    r"support[_ ]url",
    r"metadata",
]

SCREENSHOT_PATTERNS = [
    r"\bappScreenshot\b",
    r"\bscreenshotset\b",
    r"assetDeliveryState",
    r"image.*too (large|small)",
    r"invalid image",
    r"screenshot upload",
    r"upload.*screenshot",
]

VALIDATION_PATTERNS = [
    r"too long",
    r"too many characters",
    r"exceeds (the )?maximum",
    r"maximum (length|number)",
    r"must be .* characters",
    r"is invalid",
    r"cannot contain",
    r"not allowed",
]

TRANSIENT_PATTERNS = [
    r"\b429\b",
    r"too many requests",
    r"rate limit",
    r"timed out",
    r"timeout",
    r"connection (reset|refused|aborted)",
    r"temporarily unavailable",
    r"\b502\b",
    r"\b503\b",
    r"\b504\b",
    r"service unavailable",
    r"network",
]


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


COMPILED = {
    "name": _compile(NAME_PATTERNS),
    "metadata": _compile(METADATA_PATTERNS),
    "screenshot": _compile(SCREENSHOT_PATTERNS),
    "validation": _compile(VALIDATION_PATTERNS),
    "transient": _compile(TRANSIENT_PATTERNS),
}


def read_log_text(log_file: str | None) -> str:
    if not log_file:
        return ""
    path = Path(log_file)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def extract_error_lines(text: str, limit: int = 12) -> list[str]:
    if not text:
        return []

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.search(
            r"(error|failed|failure|rejected|invalid|could not|unable to|not allowed|already)",
            line,
            re.IGNORECASE,
        ):
            lines.append(line)
    if lines:
        return lines[-limit:]

    non_empty = [line.strip() for line in text.splitlines() if line.strip()]
    return non_empty[-limit:]


def summarize_message(lines: list[str], max_len: int = 220) -> str:
    if not lines:
        return "No error details captured"
    message = " | ".join(lines[-3:])
    message = re.sub(r"\s+", " ", message).strip()
    if len(message) > max_len:
        return message[: max_len - 3] + "..."
    return message


def _matches(patterns: list[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _reason(category: str, message: str, exit_code: int) -> dict[str, Any]:
    return {
        "category": category,
        "label": CATEGORY_LABELS.get(category, CATEGORY_LABELS["unknown"]),
        "message": message,
        "exit_code": exit_code,
    }


def classify_failure(
    step: str,
    exit_code: int,
    log_text: str = "",
    *,
    included_name: bool = False,
) -> dict[str, Any]:
    text = log_text or ""
    lower = text.lower()
    error_lines = extract_error_lines(text)
    message = summarize_message(error_lines)

    if "unbound variable" in lower or "paths.sh:" in lower:
        return _reason("unknown", message, exit_code)

    if _matches(COMPILED["name"], lower):
        return _reason("name_rejected", message, exit_code)

    if "non-interactive mode" in lower or "fastlanecrash" in lower:
        if step == "app_info":
            if included_name:
                return _reason("name_rejected", message, exit_code)
            return _reason("metadata_rejected", message, exit_code)
        if step == "screenshots":
            return _reason("screenshot_rejected", message, exit_code)
        if step in {"metadata", "whats_new"}:
            return _reason("metadata_rejected", message, exit_code)
        return _reason("unknown", message, exit_code)

    if step == "app_info":
        if included_name:
            return _reason("name_rejected", message, exit_code)
        return _reason("metadata_rejected", message, exit_code)

    if step == "screenshots" or _matches(COMPILED["screenshot"], lower):
        return _reason("screenshot_rejected", message, exit_code)

    if step in {"metadata", "whats_new"} or _matches(COMPILED["metadata"], lower):
        return _reason("metadata_rejected", message, exit_code)

    return _reason("unknown", message, exit_code)


def record_locale_failure(
    section: str,
    locale: str,
    step: str,
    exit_code: int,
    log_file: str | None = None,
    *,
    included_name: bool = False,
) -> dict[str, Any]:
    reason = classify_failure(
        step,
        exit_code,
        read_log_text(log_file),
        included_name=included_name,
    )
    report = load_report() or default_report()
    sections = report.setdefault("sections", {})
    current = sections.setdefault(section, {})
    if not isinstance(current, dict):
        current = {}
        sections[section] = current
    failures = current.setdefault("failed_locale_reasons", {})
    if not isinstance(failures, dict):
        failures = {}
        current["failed_locale_reasons"] = failures
    failures[locale] = reason
    save_report(report)
    return reason


def format_failure_line(locale: str, reason: dict[str, Any]) -> str:
    label = reason.get("label") or CATEGORY_LABELS.get(reason.get("category", "unknown"), "upload failed")
    message = reason.get("message") or "No error details captured"
    exit_code = reason.get("exit_code")
    if exit_code is not None:
        return f"  • {locale} — {label} (exit {exit_code}): {message}"
    return f"  • {locale} — {label}: {message}"


def cmd_record(args: argparse.Namespace) -> int:
    reason = record_locale_failure(
        args.section,
        args.locale,
        args.step,
        args.exit_code,
        args.log_file,
        included_name=args.included_name,
    )
    print(json.dumps(reason, ensure_ascii=False))
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    reason = classify_failure(
        args.step,
        args.exit_code,
        read_log_text(args.log_file),
        included_name=args.included_name,
    )
    print(json.dumps(reason, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify automation upload failures")
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record")
    record.add_argument("--section", required=True)
    record.add_argument("--locale", required=True)
    record.add_argument("--step", required=True, choices=["app_info", "metadata", "screenshots", "whats_new"])
    record.add_argument("--exit-code", type=int, required=True)
    record.add_argument("--log-file", default="")
    record.add_argument("--included-name", action="store_true")
    record.set_defaults(func=cmd_record)

    classify = sub.add_parser("classify")
    classify.add_argument("--step", required=True, choices=["app_info", "metadata", "screenshots", "whats_new"])
    classify.add_argument("--exit-code", type=int, required=True)
    classify.add_argument("--log-file", default="")
    classify.add_argument("--included-name", action="store_true")
    classify.set_defaults(func=cmd_classify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
