#!/usr/bin/env python3
"""Статус приложения в App Store для консоли: что с последней версией у Apple.

Читает версии приложения ключом аккаунта и пишет store/status.json в
репозиторий приложения — консоль показывает его иконкой App Store в списке
проектов. Сама консоль в Apple не ходит: запросы идут только из прогона.

Текста ответа App Review здесь нет и быть не может: ключ API к переписке
с ревьюером не пускает. Только состояние версии.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

STATE_VERSION = 1
# Сколько смен статуса помнить: ленте ревью в консоли больше не нужно.
KEEP_HISTORY = 30

# Состояние версии у Apple → статус в консоли. Поле appStoreState Apple
# объявила устаревшим, но отдаёт; appVersionState — новое, берём его, когда есть.
STATES = {
    "sale": {"READY_FOR_SALE", "READY_FOR_DISTRIBUTION"},
    "ok": {"PENDING_DEVELOPER_RELEASE", "PENDING_APPLE_RELEASE", "ACCEPTED", "PROCESSING_FOR_APP_STORE",
           "PROCESSING_FOR_DISTRIBUTION", "PREORDER_READY_FOR_SALE"},
    "review": {"IN_REVIEW"},
    "wait": {"WAITING_FOR_REVIEW", "READY_FOR_REVIEW", "WAITING_FOR_EXPORT_COMPLIANCE"},
    "rej": {"REJECTED", "METADATA_REJECTED", "INVALID_BINARY"},
    "prep": {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED"},
    "removed": {"REMOVED_FROM_SALE", "DEVELOPER_REMOVED_FROM_SALE", "REPLACED_WITH_NEW_VERSION"},
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status_of(raw: str | None) -> str:
    for status, names in STATES.items():
        if raw in names:
            return status
    return "unknown"


def raw_state(version: dict) -> str | None:
    attrs = version.get("attributes") or {}
    return attrs.get("appVersionState") or attrs.get("appStoreState")


def summarize(versions: list[dict]) -> dict:
    """Последняя версия, её статус и версия, которая сейчас в продаже."""
    if not versions:
        return {"status": "none", "appVersion": None, "raw": None, "live": None}
    ordered = sorted(versions, key=lambda v: (v.get("attributes") or {}).get("createdDate") or "", reverse=True)
    latest = ordered[0]
    live = next((v for v in ordered if status_of(raw_state(v)) == "sale"), None)
    raw = raw_state(latest)
    return {
        "status": status_of(raw),
        "appVersion": (latest.get("attributes") or {}).get("versionString"),
        "raw": raw,
        "live": (live.get("attributes") or {}).get("versionString") if live else None,
    }


def record(state: dict, current: dict, at: str, by: str | None) -> dict:
    """Новое состояние файла: текущий статус и история смен."""
    history = list(state.get("history") or [])
    last = history[0] if history else None
    if not last or (last.get("status"), last.get("appVersion")) != (current["status"], current["appVersion"]):
        history.insert(0, {"at": at, "status": current["status"], "appVersion": current["appVersion"], "raw": current["raw"]})
    return {
        "version": STATE_VERSION,
        **current,
        "checkedAt": at,
        "checkedBy": by,
        "changedAt": history[0]["at"],
        "history": history[:KEEP_HISTORY],
    }


def load(path: Path) -> dict:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") == STATE_VERSION:
            return data
    return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()

    from upload_screenshots_api import AppStoreConnectClient, find_app, require_env

    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=Path(require_env("ASC_KEY_PATH")),
    )
    app = find_app(client, require_env("APP_IDENTIFIER"))
    # Одна страница, без перебора всех версий за годы: нужны только последние.
    response = client.request(
        "GET",
        f"/apps/{app['id']}/appStoreVersions?filter[platform]=IOS&limit=20"
        "&fields[appStoreVersions]=versionString,appStoreState,appVersionState,createdDate",
    )
    current = summarize(response.get("data") or [])
    state = record(load(args.state), current, now(), os.environ.get("STORE_STATUS_ACTOR"))
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"App Store: {current['appVersion'] or '—'} — {current['status']} ({current['raw'] or 'нет версий'}); в продаже {current['live'] or '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
