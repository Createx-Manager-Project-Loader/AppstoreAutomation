#!/usr/bin/env python3
"""Write workflow_dispatch / env values back into config.yaml."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from paths import CONFIG_PATH

ENV_TO_CONFIG = (
    ("RUN_MODE", "run_mode"),
    ("RELEASE_NOTES", "release_notes"),
    ("GOOGLE_SHEET_URL", "google_sheet_url"),
    ("SCREENSHOTS_ZIP_URL", "screenshots_zip_url"),
)

INPUT_TO_CONFIG = (
    ("run_mode", "run_mode"),
    ("release_notes", "release_notes"),
    ("google_sheet_url", "google_sheet_url"),
    ("screenshots_zip_url", "screenshots_zip_url"),
)


def format_yaml_value(value: str) -> str:
    if not value:
        return '""'
    if re.fullmatch(r"[a-z0-9_]+", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def parse_existing_yaml_value(raw: str) -> str:
    text = raw.strip()
    if not text or text == '""':
        return ""
    if yaml is None:
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            return text[1:-1]
        return text
    try:
        loaded = yaml.safe_load(text)
        return "" if loaded is None else str(loaded)
    except yaml.YAMLError:
        return text.strip('"').strip("'")


def replace_config_key(text: str, key: str, value: str) -> tuple[str, bool]:
    pattern = re.compile(rf"^({re.escape(key)}:[ \t]*)(.*)$", re.MULTILINE)
    formatted = format_yaml_value(value)
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        old_raw = match.group(2).strip()
        old_value = parse_existing_yaml_value(old_raw)
        if old_value == value:
            return match.group(0)
        changed = True
        prefix = match.group(1).rstrip()
        return f"{prefix} {formatted}"

    updated, count = pattern.subn(repl, text, count=1)
    if count == 0:
        raise SystemExit(f"Key '{key}' not found in {CONFIG_PATH}")
    return updated, changed


def values_from_github_event() -> dict[str, str]:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not event_path or not Path(event_path).is_file():
        return {}

    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        return {}

    values: dict[str, str] = {}
    for input_key, config_key in INPUT_TO_CONFIG:
        if input_key not in inputs:
            continue
        values[config_key] = str(inputs.get(input_key) or "").strip()
    return values


def values_from_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for env_key, config_key in ENV_TO_CONFIG:
        if env_key not in os.environ:
            continue
        values[config_key] = os.environ.get(env_key, "").strip()
    return values


def values_to_persist() -> dict[str, str]:
    """Prefer step/job env (wired to inputs.*); merge with webhook payload as fallback."""
    env_values = values_from_env()
    event_values = values_from_github_event()

    if env_values:
        print(f"Using workflow env overrides ({len(env_values)} field(s)).")
        merged = dict(event_values)
        merged.update(env_values)
        return merged

    if event_values:
        print(f"Using workflow_dispatch inputs from GITHUB_EVENT_PATH ({len(event_values)} field(s)).")
        return event_values

    return {}


def persist_config() -> bool:
    if not CONFIG_PATH.is_file():
        raise SystemExit(f"Missing {CONFIG_PATH}")

    updates = values_to_persist()
    if not updates:
        print("No workflow inputs to persist.")
        return False

    text = CONFIG_PATH.read_text(encoding="utf-8")
    any_changed = False
    for key, value in updates.items():
        text, changed = replace_config_key(text, key, value)
        any_changed = any_changed or changed
        preview = value[:80] + ("..." if len(value) > 80 else "")
        status = "updated" if changed else "unchanged"
        print(f"  {key} ({status}): {preview or '(empty)'}")

    if not any_changed:
        print("config.yaml already matches workflow inputs — nothing to commit.")
        return False

    CONFIG_PATH.write_text(text, encoding="utf-8")
    print(f"Updated {CONFIG_PATH.name} from workflow inputs.")
    return True


def main() -> int:
    print("Persisting workflow inputs to config.yaml:")
    persist_config()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
