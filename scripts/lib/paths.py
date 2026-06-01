"""Shared path resolution for app-store automation scripts."""

from __future__ import annotations

import os
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = _LIB_DIR.parent
AUTOMATION_DIR = SCRIPT_DIR.parent
REPO_ROOT = AUTOMATION_DIR.parent
METADATA_DIR = REPO_ROOT / "metadata"


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


CONFIG_PATH = _path_from_env("AUTOMATION_CONFIG_PATH", REPO_ROOT / "automation-config.yaml")
PREPARED_DIR = _path_from_env("AUTOMATION_PREPARED_DIR", REPO_ROOT / "automation-prepared")
