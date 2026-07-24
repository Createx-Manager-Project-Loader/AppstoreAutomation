#!/usr/bin/env python3
"""Sync workflow_dispatch input defaults from config.yaml into the GitHub workflow."""

from __future__ import annotations

import re
import sys
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML required. Run: python -m pip install -r automation/requirements.txt")

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from paths import CONFIG_PATH, REPO_ROOT
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/app-store-automation.yml"
MARKER_START = "      # workflow-defaults:start"
MARKER_END = "      # workflow-defaults:end"
RUN_MODE_OPTIONS = ("all", "screenshots", "aso", "whats_new")
DEFAULT_RUN_MODE = "whats_new"


def read_config() -> dict[str, str]:
    loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise SystemExit(f"{CONFIG_PATH} must contain key-value settings at the top level")

    def pick(key: str) -> str:
        value = loaded.get(key)
        if value is None:
            return ""
        return str(value).strip()

    run_mode = pick("run_mode")
    if run_mode and run_mode not in RUN_MODE_OPTIONS:
        raise SystemExit(
            f"config.yaml run_mode must be one of: {', '.join(RUN_MODE_OPTIONS)} (got '{run_mode}')"
        )
    if not run_mode:
        run_mode = DEFAULT_RUN_MODE

    return {
        "run_mode": run_mode,
        "release_notes": pick("release_notes"),
        "google_sheet_url": pick("google_sheet_url"),
        "screenshots_zip_url": pick("screenshots_zip_url"),
        "asc_metadata_items": pick("asc_metadata_items"),
        "asc_only_locales": pick("asc_only_locales"),
        "asc_selection": pick("asc_selection"),
    }


def yaml_scalar(value: str) -> str:
    if value == "":
        return '""'
    return yaml.safe_dump(value, default_style='"', allow_unicode=True).strip()


def render_inputs(config: dict[str, str]) -> str:
    run_mode_default = config["run_mode"] if config["run_mode"] in RUN_MODE_OPTIONS else DEFAULT_RUN_MODE
    return "\n".join(
        [
            MARKER_START,
            "      run_mode:",
            "        required: true",
            f"        default: {yaml_scalar(run_mode_default)}",
            "        type: choice",
            "        options:",
            "          - all",
            "          - screenshots",
            "          - aso",
            "          - whats_new",
            "      release_notes:",
            "        required: false",
            f"        default: {yaml_scalar(config['release_notes'])}",
            "        type: string",
            "      google_sheet_url:",
            "        required: false",
            f"        default: {yaml_scalar(config['google_sheet_url'])}",
            "        type: string",
            "      screenshots_zip_url:",
            "        required: false",
            f"        default: {yaml_scalar(config['screenshots_zip_url'])}",
            "        type: string",
            "      asc_metadata_items:",
            "        required: false",
            f"        default: {yaml_scalar(config['asc_metadata_items'])}",
            "        type: string",
            "      asc_only_locales:",
            "        required: false",
            f"        default: {yaml_scalar(config['asc_only_locales'])}",
            "        type: string",
            "      asc_selection:",
            "        required: false",
            f"        default: {yaml_scalar(config['asc_selection'])}",
            "        type: string",
            MARKER_END,
        ]
    )


def sync_workflow() -> bool:
    if not CONFIG_PATH.is_file():
        raise SystemExit(f"Missing {CONFIG_PATH}")
    if not WORKFLOW_PATH.is_file():
        raise SystemExit(f"Missing {WORKFLOW_PATH}")

    config = read_config()
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        re.DOTALL,
    )
    replacement = render_inputs(config)
    if not pattern.search(workflow_text):
        raise SystemExit(
            f"Workflow markers not found in {WORKFLOW_PATH}. "
            f"Expected {MARKER_START} and {MARKER_END}."
        )

    updated = pattern.sub(replacement, workflow_text)
    if updated == workflow_text:
        print("Workflow defaults already match config.yaml.")
        return False

    WORKFLOW_PATH.write_text(updated, encoding="utf-8")
    print(f"Updated workflow defaults from {CONFIG_PATH.name}:")
    for key, value in config.items():
        preview = value if len(value) <= 72 else value[:69] + "..."
        print(f"  {key}: {preview or '(empty)'}")
    return True


def main() -> int:
    changed = sync_workflow()
    return 0 if changed or not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
