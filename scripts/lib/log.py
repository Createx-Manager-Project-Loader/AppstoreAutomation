#!/usr/bin/env python3
"""Console logging for automation scripts (GitHub Actions job output)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

VERBOSE = os.environ.get("AUTOMATION_VERBOSE", "1").strip().lower() not in {"0", "false", "no", "off"}
if os.environ.get("GITHUB_ACTIONS", "").lower() == "true" or os.environ.get("CI", "").lower() == "true":
    VERBOSE = True


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_info(message: str) -> None:
    print(f"[{_ts()}] INFO  {message}", flush=True)


def log_warn(message: str) -> None:
    print(f"[{_ts()}] WARN  {message}", file=sys.stderr, flush=True)


def log_error(message: str) -> None:
    print(f"[{_ts()}] ERROR {message}", file=sys.stderr, flush=True)


def log_debug(message: str) -> None:
    if VERBOSE:
        print(f"[{_ts()}] DEBUG {message}", flush=True)


def log_step(message: str) -> None:
    log_info(f"===== {message} =====")


def log_step_done(message: str, code: int = 0) -> None:
    if code == 0:
        log_info(f"===== {message}: OK (exit 0) =====")
    else:
        log_warn(f"===== {message}: FAILED (exit {code}) =====")


def truncate_text(value: str, limit: int = 300) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def log_file_summary(path: Path, label: str = "file") -> None:
    if not path.is_file():
        log_info(f"{label} missing: {path}")
        return
    content = path.read_text(encoding="utf-8", errors="replace")
    log_info(f"{label} {path} ({len(content)} chars): {truncate_text(content)}")


def log_locale_metadata_summary(locale_dir: Path) -> None:
    if not locale_dir.is_dir():
        return
    log_info(f"Locale payload {locale_dir.name}:")
    for file_name in (
        "name.txt",
        "subtitle.txt",
        "keywords.txt",
        "description.txt",
        "release_notes.txt",
        "support_url.txt",
        "marketing_url.txt",
    ):
        log_file_summary(locale_dir / file_name, f"{locale_dir.name}/{file_name}")


def log_api_request(method: str, url: str) -> None:
    log_info(f"ASC API {method} {url}")


def log_api_response(method: str, url: str, status_code: int, body: str = "") -> None:
    if status_code < 400:
        log_info(f"ASC API {method} {url} -> {status_code}")
        return
    preview = truncate_text(body or "", 1200)
    log_error(f"ASC API {method} {url} -> {status_code}: {preview}")
